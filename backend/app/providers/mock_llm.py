"""Deterministic mock LLM used when no API key is configured (and in tests).

The mock plays all three roles (sales agent, customer simulator, judge) with simple
rule-based logic. It exists to exercise the full pipeline end to end. Its outputs say
NOTHING about how real models behave, and every result produced with it is stored with
run_mode='mock' and labelled as such in the UI and reports.

Prompt strategy only influences the mock through a hash of the system prompt, which
picks between equivalent phrasings and decides when the demo is first proposed. The
mock therefore introduces no systematic advantage for any strategy.
"""

import hashlib
import json
import re
import time
from typing import Any

from app.product import FLOWDESK
from app.providers.base import LLMProvider, LLMRequest, LLMResponse

AGREE_RE = re.compile(
    r"\b(theek hai|thik hai|ok|okay|chalo|sure|book|kar do|karo|bhej do|bhejiye|done|"
    r"chalega|ji haan)\b",
    re.I,
)
OFFER_RE = re.compile(r"\b(demo|trial|slot)\b", re.I)

# (pattern, reply to first mention, reply to a repeated mention). Order matters.
_INTENTS: list[tuple[str, str, str]] = [
    (
        r"secur|safe|sensitive|cloud",
        "Ye bahut zaroori sawal hai. FlowDesk mein data encrypted rehta hai, role-based access "
        "hai, daily backup hota hai aur Indian data centres mein host hai. Aapko kaun sa data "
        "sabse sensitive lagta hai?",
        "Demo mein main access controls live dikha dungi taaki aap khud dekh sako. Kya hum is "
        "hafte ek 30 minute ka slot rakh sakte hain?",
    ),
    (
        r"migrat|shift|headache|sikhana|implementation|setup|kitna time lagta",
        "Ye tension samajh aata hai. Excel ya CSV data FlowDesk mein import ho jaata hai aur "
        "onboarding team setup mein help karti hai, aam taur par ek hafte ke aas-paas. Aapki "
        "team mein kitne log hain?",
        "Original sheet apni jagah safe rehti hai, toh data ka risk nahi. Demo mein import "
        "process dikha denge. Kab free ho aap?",
    ),
    (
        r"shuru|kaise start|sign ?up",
        "Bahut badiya! Sabse aasan tareeka 14 din ka free trial hai, bina card ke. Chaho toh "
        "main ek chhota onboarding demo bhi rakh deti hoon. Aapki team mein kitne log hain?",
        "Great, main demo slot set kar deti hoon aur trial ke steps bhej dungi. Kaunsa din "
        "theek rahega?",
    ),
    (
        r"pricing|kitna lagega|kitne user",
        "FlowDesk ke do plans hain: Starter Rs 799 aur Growth Rs 1499 per user per month. "
        "Growth mein automated follow-ups aate hain. Aapki team mein kitne log use karenge?",
        "14 din ka free trial hai, bina card ke, aur 20 se zyada users pe volume discount ke "
        "liye baat ho sakti hai. Demo mein plan fit karke dikha dungi.",
    ),
    (
        r"\bdemo\b|dekhna|dikhao",
        "Zaroor, demo ke liye main ready hoon. Aapki team mein kitne log hain aur abhi leads "
        "kahan track karte ho, taaki demo aapke process pe dikha sakun?",
        "Perfect, 30 minute ka demo rakhte hain. Aapko kab convenient rahega, kal ya parso?",
    ),
    (
        r"\bfree\b",
        "Seedha bataun toh permanent free plan nahi hai, lekin 14 din ka free trial hai, bina "
        "credit card ke. Aap kitne log use karoge?",
        "Trial mein aap apni real leads daal ke dekh sakte ho. Chaho toh ek chhota demo bhi "
        "rakh deti hoon taaki setup aasani se ho jaaye.",
    ),
    (
        r"sasta|quote|cheaper|competitor",
        "Fair point, price compare karna sahi hai. Aapke liye sabse zaroori kya hai: automated "
        "follow-ups, pipeline visibility, ya setup mein aasani?",
        "Main kisi aur tool ke baare mein kuch nahi kahungi. Bas FlowDesk ka trial lekar "
        "side-by-side dekh lo, demo mein aapke process ke hisaab se dikha denge.",
    ),
    (
        r"budget",
        "Samajh sakti hoon, budget tight ho toh software last priority hota hai. Ek lead ki "
        "value aapke liye kitni hoti hai, aur mahine mein kitni lead chhoot jaati hain?",
        "Agar ek-do deals bhi bach jaayein toh tool ka kharcha nikal jaata hai. 14 din ka free "
        "trial hai, bina card ke, toh try karne mein koi risk nahi.",
    ),
    (
        r"price|mehang|zyada|expensive|paisa",
        "Haan, price dekhna zaroori hai, main samajhti hoon. Ek baat poochun: abhi mahine mein "
        "kitni leads miss ho jaati hain, ya follow-up late hone se deals jaati hain?",
        "Isiliye 14 din ka free trial hai, bina card ke. Starter plan Rs 799 per user per "
        "month se shuru hota hai, toh pehle try karke dekh sakte ho ki fit hai ya nahi.",
    ),
    (
        r"salesforce",
        "Salesforce ek strong tool hai, usme koi shak nahi. Aapki team usse daily kaise use "
        "karti hai, aur kya cheez sabse zyada friction deti hai?",
        "Bade tool mein adoption kai teams ko mushkil lagta hai. FlowDesk simple hai: lead, "
        "pipeline aur follow-up. Dono side-by-side dekhne ke liye chhota demo kaafi rahega.",
    ),
    (
        r"zoho",
        "Zoho achha tool hai. Aap usme kya pasand karte ho, aur kya cheez thodi cluttered ya "
        "slow lagti hai?",
        "Agar kuch cheezein friction deti hain toh FlowDesk dekhna worth it hai. Data CSV "
        "export-import se aa jaata hai, onboarding team help karti hai. Ek demo rakh lein?",
    ),
    (
        r"hubspot",
        "Free plan ki limits jaldi aa jaati hain, haan. Kaun si limit sabse zyada dikkat de "
        "rahi hai: contacts, automation ya reports?",
        "FlowDesk ka Growth plan Rs 1499 per user per month hai aur automated follow-ups usme "
        "included hain. HubSpot se data CSV export karke import ho jaata hai. Demo dekhna "
        "chahoge?",
    ),
    (
        r"internal tool|apna tool|banwaya",
        "Achha hai ki aapne apna tool banwa liya. Wo tool maintain kaun karta hai, aur naye "
        "features chahiye ho toh kitna time lagta hai?",
        "Aksar internal tool ek hi developer pe depend karta hai. FlowDesk mein ye sab ready "
        "hai. Ek chhota demo dekh lo, phir tulna kar lena.",
    ),
    (
        r"suna nahi|kaun si company|never heard",
        "Bilkul valid sawal hai. FlowDesk chhote aur medium businesses ke liye CRM aur "
        "follow-up automation tool hai. Aap abhi leads kaise track karte ho, taaki main sahi "
        "se bata sakun?",
        "Risk kam rakhne ke liye 14 din ka free trial hai, bina card ke. Aap khud try karke "
        "dekh lo, aur chaho toh ek demo bhi kara deti hoon.",
    ),
    (
        r"busy|next month|baad mein|time nahi",
        "Bilkul, main aapka time nahi lungi. Kya ek 15 minute ka quick slot next week rakh "
        "sakte hain, jab aap free ho?",
        "Koi baat nahi, main short rakhti hoon. Aap bas ek din aur time bata do, main demo us "
        "hisaab se set kar dungi.",
    ),
    (
        r"soch|think",
        "Zaroor, soch lijiye. Koi specific cheez abhi clear nahi hai: price, setup ya team "
        "adoption? Main uspe seedha bata sakti hoon.",
        "Sochne ke liye 14 din ka free trial best hai, bina card ke. Chaho toh ek chhota demo "
        "bhi rakh lete hain, phir decide karna.",
    ),
    (
        r"manager|boss|approval|director|decision",
        "Samajh gaya. Aapke manager ko sabse zyada kya important lagta hai: cost, team "
        "adoption ya reporting?",
        "Ek kaam karte hain, manager ko bhi demo mein jod lete hain, toh unke sawal wahin "
        "clear ho jaayenge. Kaunsa din theek rahega?",
    ),
    (
        r"bekaar|waste|use hi nahi|pehle bhi",
        "Aapka anubhav samajh sakti hoon, aksar tool isliye fail hota hai kyunki team use "
        "nahi karti. Pichle CRM mein sabse badi dikkat kya thi?",
        "Isiliye FlowDesk simple rakha hai: kam clicks, automatic reminders. Ek demo mein "
        "dekh lo, pasand na aaye toh koi baat nahi.",
    ),
    (
        r"\bipl\b|cricket|jeetega|movie|politics",
        "Ha ha, IPL mein toh sab close hai! Waise aapke business ki baat karein: leads abhi "
        "kaise track karte ho?",
        "Chalo wapas kaam pe. FlowDesk mein leads aur follow-ups ek jagah dikhte hain. Ek "
        "chhota demo rakh lein?",
    ),
    (
        r"excel|sheet",
        "Haan, kaafi businesses shuru mein Excel se hi chalate hain. Ek cheez samajhna "
        "chahungi: follow-ups aur lead status track karna Excel mein easy lagta hai, ya "
        "kabhi-kabhi leads miss bhi ho jaati hain?",
        "Samajh gaya. FlowDesk mein har lead ka status aur next follow-up ek jagah dikhta hai "
        "aur reminder automatically aata hai, toh leads sheet mein kho nahi jaati. Aapki team "
        "mein kitne log leads handle karte hain?",
    ),
    (
        r"koi crm nahi|diary|no crm",
        "Bilkul, chhoti teams mein diary aur chat se hi kaam chalta hai. Mahine mein kitni "
        "leads aati hain, aur unka follow-up yaad kaun rakhta hai?",
        "Isiliye FlowDesk simple rakha hai: lead daalo, owner assign karo, aur follow-up "
        "reminder set ho jaata hai. Onboarding team import mein help karti hai.",
    ),
    (
        r"track rakhna|ho gayi hai|team",
        "Team badhne pe yahi hota hai, leads ka ownership dhundhna mushkil ho jaata hai. "
        "Leads abhi kaun kisko assign karta hai, aur follow-up ka status kahan dekhte ho?",
        "FlowDesk mein har lead ka owner aur stage clear dikhta hai, toh manager ko ek hi "
        "screen pe poori pipeline mil jaati hai.",
    ),
]
_ONE_WORD = (
    "Theek hai. Chhota sa sawal: aap leads abhi Excel mein rakhte ho ya kisi tool mein?",
    "Samajh gaya. Kya aapki team mein 5 se zyada log leads handle karte hain?",
)
_CONTINUE = (
    "Accha, ye helpful hai. Ek cheez aur: follow-up ke reminders abhi kaun set karta hai?",
    "Samajh gaya. FlowDesk mein pipeline stages aur tasks ek jagah milte hain, toh kuch miss "
    "nahi hota. Aapko sabse zyada kya useful lagega?",
    "Theek hai. Team ko ek baar live dekhna kaafi rahega, kya hum chhota demo rakh sakte hain?",
)
_DEMO_CTA = (
    "Agar chaho toh ek 30 minute ka demo rakh sakte hain, aapke hi process pe FlowDesk "
    "dikhaungi. Kaise rahega?",
    "Kya main aapke liye ek chhota demo slot set kar doon? Aapke process ke hisaab se dikhaungi.",
)
_CLOSE = (
    "Perfect, main demo slot confirm kar deti hoon. Aap apna email bata dijiye, main "
    "calendar invite bhej dungi.",
    "Badhiya! Main kal ke liye slot rakh deti hoon. Confirmation ke liye email ya number "
    "share kar dijiye.",
)

_PUSHBACK = {
    "discovery": (
        "Haan par abhi toh sab theek hi chal raha hai, kya zaroorat hai?",
        "Achha, aur kya kya kar sakta hai ye?",
        "Hmm, team adopt karegi ya nahi, pata nahi.",
    ),
    "price_objection": (
        "Par phir bhi price mere hisaab se zyada hai.",
        "Koi discount milega kya?",
        "Hmm, pehle kuch dikhao toh sahi.",
    ),
    "existing_solution": (
        "Par humara current tool bhi toh kaam kar raha hai.",
        "Switch karne mein time lagega na?",
        "Hmm, aur kya alag hai isme?",
    ),
    "trust": (
        "Par mujhe abhi bhi thoda doubt hai.",
        "Koi proof ya reference hai kya?",
        "Hmm, theek hai, aur batao.",
    ),
    "timing": (
        "Par abhi mera time nahi hai.",
        "Kitna time lagega ismein?",
        "Hmm, thoda sochna padega.",
    ),
    "buying_intent": (
        "Aur kuch jaanna hai: setup kaise hoga?",
        "Aur plans mein kya difference hai?",
        "Achha, aur batao.",
    ),
    "difficult_customer": (
        "Jaldi bolo, kya chahiye aapko?",
        "Mujhe nahi lagta iski zaroorat hai.",
        "Hmm.",
    ),
}
_AGREE = (
    "Theek hai, demo book kar do.",
    "Chalo, ek demo dekh lete hain. Kal ka slot bhej do.",
    "Ok, free trial bhi shuru karte hain, aur demo bhi rakh lo.",
)


def _h(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


class MockLLMProvider(LLMProvider):
    name = "mock"
    is_mock = True

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        if request.task == "agent":
            text = self._agent(request)
        elif request.task == "simulator":
            text = self._simulator(request)
        else:
            text = self._judge(request)
        return LLMResponse(
            text=text, latency_ms=(time.perf_counter() - start) * 1000, model="mock-llm"
        )

    # ------------------------------------------------------------------ agent
    def _agent(self, req: LLMRequest) -> str:
        customer_msgs = [m.content for m in req.messages if m.role == "user"]
        agent_msgs = [m.content for m in req.messages if m.role == "assistant"]
        last = customer_msgs[-1] if customer_msgs else ""
        k = len(customer_msgs)
        seed = _h(req.system)
        offered_before = any(OFFER_RE.search(a) for a in agent_msgs)

        if offered_before and AGREE_RE.search(last):
            return _CLOSE[_h(seed, k) % len(_CLOSE)]

        if len(last.split()) <= 2 and not any(re.search(p, last, re.I) for p, _, _ in _INTENTS):
            reply = _ONE_WORD[(k - 1) % len(_ONE_WORD)]
        else:
            reply = _CONTINUE[_h(seed, k) % len(_CONTINUE)]
            if k <= 2:  # intent-specific answers for the opening exchanges only
                for pattern, first, repeat in _INTENTS:
                    if re.search(pattern, last, re.I):
                        reply = first if k == 1 else repeat
                        break

        demo_after = 2 + seed % 5
        if k >= demo_after and not OFFER_RE.search(reply):
            reply = f"{reply} {_DEMO_CTA[_h(seed, k) % len(_DEMO_CTA)]}"
        return reply

    # -------------------------------------------------------------- simulator
    def _simulator(self, req: LLMRequest) -> str:
        scenario: dict[str, Any] = req.metadata["scenario"]
        agent_msgs = [m.content for m in req.messages if m.role == "user"]
        # From the simulator's point of view the *agent* is the "user" speaking to it.
        k = len(agent_msgs)
        last_agent = agent_msgs[-1] if agent_msgs else ""
        difficulty = int(scenario["difficulty"])
        one_word = scenario["id"] == "diff-one-word"

        offered = bool(OFFER_RE.search(last_agent))
        need = max(2, 1 + (difficulty + 1) // 2)
        resist = _h(scenario["id"], k) % 100 < difficulty * 18
        if offered and k >= need and not resist:
            msg = "Haan, theek hai." if one_word else _AGREE[_h(scenario["id"], k) % len(_AGREE)]
            return json.dumps({"message": msg, "goal_reached": True, "wants_to_end": False})

        if k >= 6 and not offered and difficulty >= 4:
            return json.dumps(
                {
                    "message": "Chhodo, mujhe abhi interest nahi hai.",
                    "goal_reached": False,
                    "wants_to_end": True,
                }
            )

        if one_word:
            msg = ("Haan.", "Hmm.", "Pata nahi.", "Theek.")[(k - 1) % 4]
        else:
            bank = _PUSHBACK[scenario["category"]]
            msg = bank[_h(scenario["id"], k) % len(bank)]
        return json.dumps({"message": msg, "goal_reached": False, "wants_to_end": False})

    # ------------------------------------------------------------------ judge
    def _judge(self, req: LLMRequest) -> str:
        scenario: dict[str, Any] = req.metadata["scenario"]
        transcript: list[dict[str, str]] = req.metadata["transcript"]
        agent_texts = [t["text"] for t in transcript if t["speaker"] == "agent"]
        customer_texts = [t["text"] for t in transcript if t["speaker"] == "customer"]

        offered = any(OFFER_RE.search(t) for t in agent_texts)
        agreed = offered and any(AGREE_RE.search(t) for t in customer_texts[-2:])
        goal = 2 if agreed else 1 if offered else 0

        objection = scenario.get("expected_objection")
        if not objection or "no clear objection" in objection.lower():
            objection_score = None
        else:
            early = agent_texts[:2]
            joined = " ".join(early)
            ack = bool(
                re.search(r"samajh|haan|bilkul|fair|zaroor|sahi|achha|badhiya", joined, re.I)
            )
            question = "?" in joined
            specific = bool(
                re.search(r"flowdesk|trial|plan|import|follow-up|pipeline|demo|rs \d", joined, re.I)
            )
            objection_score = min(3, int(ack) + int(question) + int(specific))

        quality = 2
        lengths = [len(t) for t in agent_texts] or [0]
        hinglish = sum(
            bool(re.search(r"(hai|hain|aap|main|kya|toh|mein|ke|ka)", t, re.I))
            for t in agent_texts
        )
        asks = sum("?" in t for t in agent_texts)
        if agent_texts and hinglish / len(agent_texts) >= 0.7:
            quality += 1
        if 60 <= sum(lengths) / len(lengths) <= 350:
            quality += 1
        if agent_texts and asks / len(agent_texts) >= 0.5:
            quality += 1
        if len(set(agent_texts)) < len(agent_texts):
            quality -= 1  # verbatim repetition
        if max(lengths) > 450 or re.search(
            r"greetings|delighted|kindly", " ".join(agent_texts), re.I
        ):
            quality -= 1
        quality = max(1, min(5, quality))

        lowered = " ".join(agent_texts).lower()
        # A term followed by "nahi" is a denial ("permanent free plan nahi hai"), not a claim.
        invented = any(
            re.search(rf"\b{re.escape(t)}\b(?!.{{0,25}}\bnahi\b)", lowered)
            for t in FLOWDESK.forbidden_claim_terms
        )

        return json.dumps(
            {
                "goal_completion_score": goal,
                "objection_handling_score": objection_score,
                "conversation_quality_score": quality,
                "invented_claims": invented,
                "reasoning": (
                    "MOCK heuristic judge (keyword rules, not a language model): "
                    f"demo/trial offered={offered}, customer agreed={agreed}, "
                    f"{len(agent_texts)} agent turns."
                ),
            }
        )
