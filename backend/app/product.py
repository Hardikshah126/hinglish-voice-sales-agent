"""Central FlowDesk product specification.

Every prompt, scenario check and evaluator rubric reads product facts from here, so
nothing about the product is duplicated across the codebase.
"""

from pydantic import BaseModel


class Plan(BaseModel):
    name: str
    price_inr_per_user_month: int
    highlights: list[str]


class ProductSpec(BaseModel):
    name: str
    tagline: str
    description: str
    target_customers: str
    capabilities: list[str]
    not_offered: list[str]
    plans: list[Plan]
    pricing_notes: list[str]
    security: list[str]
    onboarding: list[str]
    demo: str
    # Terms that signal an invented capability if an agent claims them. Used by the mock
    # judge heuristic; the real judge receives the full fact sheet instead.
    forbidden_claim_terms: list[str]

    def fact_sheet(self) -> str:
        """Plain-text product brief shared verbatim by every prompt variant."""
        lines = [
            f"{self.name} — {self.tagline}",
            self.description,
            f"Target customers: {self.target_customers}",
            "",
            "What FlowDesk does:",
            *[f"- {c}" for c in self.capabilities],
            "",
            "What FlowDesk does NOT do (never claim these):",
            *[f"- {c}" for c in self.not_offered],
            "",
            "Pricing (INR, per user per month):",
            *[
                f"- {p.name}: Rs {p.price_inr_per_user_month} — {'; '.join(p.highlights)}"
                for p in self.plans
            ],
            *[f"- {n}" for n in self.pricing_notes],
            "",
            "Security and data:",
            *[f"- {s}" for s in self.security],
            "",
            "Onboarding and migration:",
            *[f"- {o}" for o in self.onboarding],
            "",
            f"Demo: {self.demo}",
        ]
        return "\n".join(lines)


FLOWDESK = ProductSpec(
    name="FlowDesk",
    tagline="CRM and workflow automation for small and medium businesses",
    description=(
        "FlowDesk helps growing businesses replace spreadsheet-based sales workflows with "
        "one place to manage leads, track the sales pipeline, and automate follow-ups."
    ),
    target_customers="Small and medium businesses (roughly 5 to 200 employees) with a sales team.",
    capabilities=[
        "Lead management: capture leads manually, via web forms or CSV/Excel import; assign "
        "owners; track lead status and source",
        "Sales pipeline tracking: customisable stages, kanban board view, deal values and "
        "stage-wise reports",
        "Automated follow-ups: reminders and templated email follow-ups triggered by stage "
        "changes or lead inactivity, so leads do not slip through",
        "Customer management: contact and company records with notes and full interaction history",
        "Task management: tasks with owners, due dates and reminders, linked to leads and deals",
        "Spreadsheet replacement: import existing Excel/CSV data and move the team off "
        "scattered sheets",
    ],
    not_offered=[
        "No built-in calling / telephony or WhatsApp messaging",
        "No accounting, invoicing or GST billing",
        "No marketing automation / bulk email campaigns",
        "No AI lead scoring or predictive analytics",
        "No native mobile app (the web app works on mobile browsers)",
        "No direct one-click integrations with Salesforce, Zoho or HubSpot "
        "(data moves over CSV export/import)",
        "No permanent free plan",
    ],
    plans=[
        Plan(
            name="Starter",
            price_inr_per_user_month=799,
            highlights=["lead and customer management", "basic pipeline", "tasks and reminders"],
        ),
        Plan(
            name="Growth",
            price_inr_per_user_month=1499,
            highlights=[
                "everything in Starter",
                "automated follow-up sequences",
                "custom pipeline stages and reports",
            ],
        ),
    ],
    pricing_notes=[
        "14-day free trial on both plans, no credit card needed",
        "Annual billing gives 2 months free",
        "Teams of 20+ users can ask for a volume discount",
    ],
    security=[
        "Data encrypted in transit and at rest",
        "Role-based access control so each team member sees only what they should",
        "Daily automated backups",
        "Hosted in Indian data centres",
    ],
    onboarding=[
        "Typical setup takes about a week for a small team",
        "The onboarding team helps import Excel/CSV data and set up pipeline stages",
        "Data from other CRMs can be brought in through their CSV exports",
    ],
    demo=(
        "A 30-minute live demo with a FlowDesk product specialist, tailored to the "
        "customer's current sales process."
    ),
    forbidden_claim_terms=[
        "whatsapp",
        "telephony",
        "dialer",
        "invoice",
        "invoicing",
        "gst",
        "accounting",
        "ai lead scoring",
        "predictive",
        "mobile app",
        "play store",
        "one-click integration",
        "free forever",
        "permanent free",
        "lifetime free",
        "salesforce integration",
        "zoho integration",
        "hubspot integration",
    ],
)
