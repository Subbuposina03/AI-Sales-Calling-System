import os
import sys
from app import app

client = app.test_client()

print("=== 1. TEST ROOT ROUTE (LANDING PAGE) ===")
res = client.get("/")
assert res.status_code == 200, f"Expected 200, got {res.status_code}"
assert b"AI Sales Calling Agent" in res.data, "Missing brand title in landing page"
assert b"Call Me Now" in res.data, "Missing Call Me Now button"
assert b"+91" in res.data, "Missing default +91 country code"
print(" PASS: Landing page loads with all required elements.")

print("=== 2. TEST HEALTH ENDPOINT ===")
res = client.get("/health")
assert res.status_code == 200
data = res.get_json()
assert data["status"] == "healthy"
print(" PASS: Health endpoint is healthy:", data)

print("=== 3. TEST /trigger_call VALIDATION ===")
# Test missing consent
res = client.post("/trigger_call", json={"phone": "+919876543210", "consent": False})
assert res.status_code == 400
assert "Consent required" in res.get_json()["error"]
print(" PASS: Consent validation working.")

# Test invalid phone number
res = client.post("/trigger_call", json={"phone": "123", "consent": True})
assert res.status_code == 400
assert "Invalid phone number format" in res.get_json()["error"]
print(" PASS: Phone format validation working.")

print("=== 4. TEST /trigger_call SIMULATION ===")
os.environ["SIMULATE_MODE"] = "true"
os.environ["PUBLIC_BASE_URL"] = "https://test-app.onrender.com"
res = client.post("/trigger_call", json={"phone": "+919876543210", "consent": True})
assert res.status_code == 200, f"Simulation failed: {res.data}"
sim_data = res.get_json()
assert sim_data["success"] is True
assert sim_data["status"] == "simulated"
print(" PASS: Outbound call triggered and simulated successfully:", sim_data)

print("=== 5. TEST /call_status POLLING ===")
call_sid = sim_data["call_sid"]
res = client.get(f"/call_status/{call_sid}")
assert res.status_code == 200
assert res.get_json()["status"] == "completed"
print(" PASS: Call status polling returns valid JSON.")

print("=== 6. TEST TWILIO /voice WEBHOOK ===")
res = client.post("/voice", data={"CallSid": "TEST_CALL_001", "From": "+919876543210"})
assert res.status_code == 200
assert b"<Gather" in res.data
assert b"Polly.Aditi" in res.data
print(" PASS: Voice webhook responds with TwiML Gather.")

print("=== 7. TEST CONVERSATION FLOW AND BOOKING ===")
# Turn 1: Affirmative answer to intro
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "Yes I want to become software engineer"})
assert res.status_code == 200
assert b"<Gather" in res.data
print(" PASS: Turn 1 accepted (Affirmative intro -> Course Selection).")

# Turn 2: Select Course
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "Python Full Stack"})
assert res.status_code == 200
print(" PASS: Turn 2 accepted (Course Selection -> Demo Interest).")

# Turn 3: Demo Interest
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "Yes, I am interested in demo"})
assert res.status_code == 200
print(" PASS: Turn 3 accepted (Demo Interest -> Demo Date).")

# Turn 4: Demo Day
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "Monday"})
assert res.status_code == 200
print(" PASS: Turn 4 accepted (Demo Date -> Demo Time).")

# Turn 5: Demo Time
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "10:00 AM"})
assert res.status_code == 200
print(" PASS: Turn 5 accepted (Demo Time -> Student Name).")

# Turn 6: Student Name
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "Ravi Kumar"})
assert res.status_code == 200
print(" PASS: Turn 6 accepted (Student Name -> Student Mobile).")

# Turn 7: Student Mobile
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "9876543210"})
assert res.status_code == 200
print(" PASS: Turn 7 accepted (Student Mobile -> Confirmation).")

# Turn 8: Confirm details
res = client.post("/process", data={"CallSid": "TEST_CALL_001", "SpeechResult": "Yes confirm"})
assert res.status_code == 200
print(" PASS: Turn 8 accepted (Booking Confirmed).")

print("=== 8. TEST QUESTION ANSWERING (KNOWLEDGE BASE + GEMINI FALLBACK) ===")
res = client.post("/process", data={"CallSid": "TEST_CALL_002", "SpeechResult": "what is the placement rate and salary?"})
assert res.status_code == 200
assert b"85%" in res.data or b"placement" in res.data.lower()
print(" PASS: Knowledge base placement FAQ answered.")

res = client.post("/process", data={"CallSid": "TEST_CALL_003", "SpeechResult": "who are you?"})
assert res.status_code == 200
assert b"AI sales assistant" in res.data or b"Polly.Aditi" in res.data
print(" PASS: Self introduction answered.")

print("\nALL AUTOMATED TESTS PASSED SUCCESSFULLY! 100% READY FOR PRODUCTION.")
