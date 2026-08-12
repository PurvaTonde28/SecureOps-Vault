import sys, os, json, time
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from supabase import create_client
from app.database import get_user_scoped_client
from app.retrieval import hybrid_search
from app.rerank import rerank
from app.generation import generate_answer, judge_answer
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]

with open(os.path.join(os.path.dirname(__file__), "golden_set.json")) as f:
    golden_set = json.load(f)

results = []

for case in golden_set:
    # Log in as this test case's user for real — same as a real request would,
    # so RLS is genuinely exercised, not bypassed with service_role.
    auth_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    session = auth_client.auth.sign_in_with_password({
        "email": case["tenant_email"], "password": case["tenant_password"],
    })
    user_client = get_user_scoped_client(session.session.access_token)

    candidates = hybrid_search(user_client, case["query"], match_count=20)
    top_chunks = rerank(case["query"], candidates, top_n=3)

    if not top_chunks:
        actual_answer = "No accessible documents matched your query."
        actual_sufficient = False
    else:
        result = generate_answer(case["query"], top_chunks)
        actual_answer = result.answer
        actual_sufficient = result.sufficient_context

    verdict = judge_answer(
        query=case["query"],
        expected_answer=case["expected_answer"],
        actual_answer=actual_answer,
        actual_sufficient=actual_sufficient,
        expect_sufficient=case["expect_sufficient_context"],
    )

    results.append({"id": case["id"], **verdict, "actual_answer": actual_answer})
    time.sleep(1)  # small pause between cases to stay comfortably under Groq's free-tier rate limits

# ---- Report ----
passed = sum(1 for r in results if r["passed"])
print(f"\n{'='*50}\nEVAL RESULTS: {passed}/{len(results)} passed\n{'='*50}\n")
for r in results:
    status = "PASS" if r["passed"] else "FAIL"
    print(f"[{status}] {r['id']}")
    if not r["passed"]:
        print(f"       reasoning: {r['reasoning']}")
        print(f"       context flag correct: {r['context_flag_correct']}")
        print(f"       actual answer: {r['actual_answer'][:150]}")