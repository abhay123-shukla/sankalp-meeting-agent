from typing import List
from models import SampleMeeting, SamplesResponse

SAMPLE_MEETINGS: List[SampleMeeting] = [
    SampleMeeting(
        id="sample_meet_1",
        day="Monday",
        title="Product Kickoff (Mon)",
        date="2026-11-23",
        summary="Locks Payments API on Stripe, v1 launch Nov 28, 2026 (Owner: Rahul). Priya owns Auth flow (due Nov 25).",
        expected_behavior="Extracts 2 initial active decisions (Payments API: Stripe, v1 Launch Date: 2026-11-28) and 1 action item for Priya (Auth flow, due Nov 25). No conflicts.",
        transcript="""Rahul: Welcome team to the Product Kickoff. Let's lock in our core architecture and timeline for the upcoming v1 release.
Rahul: First key decision: We are officially locking the Payments API on Stripe. It is proven, supports multi-currency, and meets our initial compliance criteria.
Priya: Makes sense. I'll take full ownership of the Auth flow and user onboarding authentication. My due date is Nov 25, 2026.
Rahul: Perfect. For the launch schedule, target v1 launch date is Nov 28, 2026. Rahul will own the launch schedule and coordination.
Rahul: Awesome. Let's make sure Stripe webhook secrets are secured in our vault before we proceed."""
    ),
    SampleMeeting(
        id="sample_meet_2",
        day="Wednesday",
        title="Tech Sync (Wed)",
        date="2026-11-25",
        summary="Priya switches Payments API to Razorpay due to Stripe KYC delays and moves v1 launch to Dec 5, 2026. Rahul assigns API webhook testing to Ankit (due Dec 2). -> MUST trigger 2 conflicts against Meeting 1 decisions in SQLite.",
        expected_behavior="Triggers 2 HIGH severity memory conflicts against Meeting 1: (1) Payments API override: Stripe -> Razorpay, (2) Launch deadline shift: Nov 28 -> Dec 5, 2026. Creates new task for Ankit.",
        transcript="""Priya: Team, we hit a major roadblock with Stripe. KYC verification is taking 3 to 4 weeks in our operating region.
Priya: Because of these Stripe KYC delays, I propose we switch the Payments API to Razorpay immediately to stay on track.
Rahul: Agreed on Razorpay, it unblocks payments right away. However, switching payment gateways requires extra work and rebuilding webhooks. We need to move the v1 launch date to Dec 5, 2026.
Priya: Makes sense. Moving the launch date to Dec 5 gives us adequate buffer. Rahul, who will handle testing the new gateway webhooks?
Rahul: Ankit, can you handle testing the new API webhooks and payment integration by Dec 2, 2026?
Ankit: Absolutely, I'll take ownership of the API webhook testing and integration tests by Dec 2, 2026."""
    ),
    SampleMeeting(
        id="sample_meet_3",
        day="Friday",
        title="Design & QA Sync (Fri)",
        date="2026-11-27",
        summary="Ankit mentions finalizing onboarding UI before launch with missing owner/deadline (flag in amber) and confirms Razorpay sandbox is live.",
        expected_behavior="Detects Razorpay sandbox is live. Extracts onboarding UI action item with NO assigned owner and NO deadline -> automatically flagged in AMBER.",
        transcript="""Ankit: Good morning everyone. A quick verification update: the Razorpay sandbox environment is now live and our test transactions are passing smoothly.
Rahul: Excellent news on the Razorpay sandbox verification! How are we doing on the onboarding screens and user experience?
Ankit: The core payment forms look solid. However, someone really needs to finalize the onboarding UI before launch.
Priya: Yes, the onboarding UI flows are critical, but we don't have anyone assigned yet and we haven't set a hard deadline for it.
Rahul: That's a clear gap. Let's flag that so it doesn't slip through the cracks before launch."""
    )
]

def get_sample_meetings() -> SamplesResponse:
    return SamplesResponse(samples=SAMPLE_MEETINGS)
