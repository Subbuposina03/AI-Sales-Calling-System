import os
import time
from collections import defaultdict
from flask import Flask, request, render_template, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv

# Import our custom systems
from knowledge_base import COURSE_INFO, FAQS
from question_answerer import detect_question_type, generate_answer
from sales_intelligence import (
    get_intro_message, get_interest_check, get_yes_response, get_no_response,
    get_answer_intro, get_after_answer, get_demo_message, get_close, handle_objection
)
from course_booking import (
    get_course_selection, get_course_confirmation, get_demo_booking,
    get_demo_time, get_booking_confirmation, get_closing,
    extract_course, extract_day, extract_time
)
from booking_system import create_booking
from call import make_outbound_call, normalize_phone_number, validate_e164_phone

app = Flask(__name__)
load_dotenv()

print("=" * 70)
print("🔥 ADVANCED AI SALES CALLING AGENT - PRODUCTION READY")
print("✅ Automated Outbound Calling via Twilio REST API")
print("✅ Gemini AI + Knowledge Base Sales Counseling")
print("✅ Course Selection & Demo Slot Booking Automation")
print("=" * 70)

# =============================
# IN-MEMORY RATE LIMITING & SECURITY
# =============================
ip_request_timestamps = defaultdict(list)
phone_call_timestamps = {}
active_call_sids = {}

def get_client_ip():
    """Retrieve client IP address accounting for reverse proxies (Render, Cloudflare, etc.)."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"

def is_ip_rate_limited(ip: str, max_requests: int = 6, window_seconds: int = 600) -> bool:
    """Limit each IP to max_requests within window_seconds."""
    now = time.time()
    recent = [t for t in ip_request_timestamps[ip] if now - t < window_seconds]
    ip_request_timestamps[ip] = recent
    if len(recent) >= max_requests:
        return True
    ip_request_timestamps[ip].append(now)
    return False

def check_phone_cooldown(phone: str, cooldown_seconds: int = 120):
    """Prevent spamming calls to the same phone number within cooldown period."""
    now = time.time()
    last_call = phone_call_timestamps.get(phone)
    if last_call and (now - last_call < cooldown_seconds):
        remaining = int(cooldown_seconds - (now - last_call))
        return False, remaining
    phone_call_timestamps[phone] = now
    return True, 0


# =============================
# CALL STATE TRACKING
# =============================
call_state = {}
conversation_history = {}
turn_count = {}
student_interest = {}
student_phone = {}

def get_state(call_id):
    return call_state.get(call_id, {
        "stage": "intro",
        "questions_asked": 0,
        "demo_offered": False,
        "course_selected": None,
        "demo_date": None,
        "demo_time": None,
        "student_name": None,
        "student_mobile": None
    })

def update_state(call_id, state):
    call_state[call_id] = state

def is_affirmative(text):
    text_lower = text.lower()
    return any(word in text_lower for word in ["yes", "ya", "yup", "sure", "okay", "of course", "absolutely", "want", "i do", "నేను", "అవును", "సరే", "yes please"])

def is_negative(text):
    text_lower = text.lower()
    return any(word in text_lower for word in ["no", "don't", "dont", "nah", "not interested", "కాదు", "లేదు", "no thanks"])

def add_to_history(call_id, role, text):
    if call_id not in conversation_history:
        conversation_history[call_id] = []
    conversation_history[call_id].append({"role": role, "text": text})

def get_turn(call_id):
    return turn_count.get(call_id, 0)

def increment_turn(call_id):
    turn_count[call_id] = get_turn(call_id) + 1

def get_stage_followup_prompt(state):
    stage = state.get("stage", "intro")
    if stage == "intro":
        return get_interest_check()
    elif stage == "course_selection":
        return get_course_selection()
    elif stage == "demo_interest":
        return get_demo_booking(state.get("course_selected"))
    elif stage == "demo_date_selection":
        return get_demo_booking(state.get("course_selected"))
    elif stage == "demo_time_selection":
        return get_demo_time()
    elif stage == "collect_student_details":
        if state.get("student_name") is None:
            return "నీ పేరు చెప్పు బ్రో, please."
        elif state.get("student_mobile") is None:
            return "నీ mobile number ఇవ్వండి బ్రో."
        else:
            return "ఇది correct కాదా బ్రో? yes or no చెప్పు బ్రో."
    return get_after_answer()

def try_general_question_response(response, call_id, user_input, state):
    question_type, direct_answer = detect_question_type(user_input)
    if question_type == "unclear":
        return False

    if direct_answer:
        ai_response = direct_answer
    else:
        ai_response = generate_answer(question_type, user_input)

    if question_type not in ["who_are_you", "what_can_you_do"]:
        ai_response = get_answer_intro(question_type) + " " + ai_response

    response.say(ai_response, voice="Polly.Aditi", language="en-IN")
    add_to_history(call_id, "Agent", ai_response)

    follow_up = get_stage_followup_prompt(state)
    gather = Gather(
        input="speech",
        action="/process",
        method="POST",
        timeout=10,
        speechTimeout="auto",
        language="en-IN"
    )
    gather.say(follow_up, voice="Polly.Aditi", language="en-IN")
    response.append(gather)
    return True


# =============================
# PUBLIC WEB ROUTES
# =============================
@app.route("/", methods=["GET"])
def home():
    """Main responsive landing page for the AI Sales Calling Agent."""
    default_phone = os.getenv("STUDENT_PHONE_NUMBER", "").strip()
    return render_template("index.html", default_phone=default_phone)

@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Backwards compatibility for /dashboard route."""
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for deployment monitoring."""
    public_url = os.getenv("PUBLIC_BASE_URL", "").strip() or request.host_url.rstrip("/")
    return jsonify({
        "status": "healthy",
        "service": "AI Sales Calling Agent",
        "public_base_url": public_url,
        "configured_twilio": bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "configured_gemini": bool(os.getenv("GEMINI_API_KEY"))
    }), 200


# =============================
# TRIGGER CALL ENDPOINT
# =============================
@app.route("/trigger_call", methods=["POST"])
def trigger_call():
    """
    Initiate an automated outbound AI sales call to the submitted phone number.
    Expects JSON: { "phone": "+919876543210", "consent": true }
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    phone_input = data.get("phone", "").strip()
    consent = data.get("consent")

    # 1. Validate Consent
    if consent not in [True, "true", "1", 1, "on"]:
        return jsonify({
            "success": False,
            "error": "Consent required: Please confirm you agree to receive an automated AI demonstration phone call."
        }), 400

    # 2. Validate Phone Input
    if not phone_input:
        return jsonify({
            "success": False,
            "error": "Phone number is required."
        }), 400

    normalized_phone = normalize_phone_number(phone_input)
    if not validate_e164_phone(normalized_phone):
        return jsonify({
            "success": False,
            "error": f"Invalid phone number format: '{phone_input}'. Please enter a valid mobile number with country code, e.g. +91 9876543210."
        }), 400

    # 3. IP Rate Limiting
    client_ip = get_client_ip()
    if is_ip_rate_limited(client_ip):
        return jsonify({
            "success": False,
            "error": "Too many call requests from your IP. Please wait 10 minutes before trying again."
        }), 429

    # 4. Duplicate / Cooldown Check for Phone Number
    allowed, remaining = check_phone_cooldown(normalized_phone, cooldown_seconds=120)
    if not allowed:
        return jsonify({
            "success": False,
            "error": f"A call was recently initiated to {normalized_phone}. Please wait {remaining} seconds before requesting another call."
        }), 429

    # 5. Resolve Public Webhook URL
    # Priority: PUBLIC_BASE_URL env -> VOICE_WEBHOOK_URL env -> Dynamic request host (with SSL check)
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    webhook_url = None
    if public_base_url:
        webhook_url = f"{public_base_url}/voice"
    elif os.getenv("VOICE_WEBHOOK_URL"):
        webhook_url = os.getenv("VOICE_WEBHOOK_URL").strip()
    else:
        # Dynamically determine host URL (Render / reverse proxy support)
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)
        host = request.headers.get("X-Forwarded-Host", request.host)
        webhook_url = f"{proto}://{host}/voice"

    print(f"\n[Trigger Call] Initiating call to {normalized_phone} using webhook: {webhook_url}")

    # 6. Execute Outbound Call via refactored call module
    result = make_outbound_call(
        to_phone_number=normalized_phone,
        webhook_url=webhook_url
    )

    if result["success"]:
        call_sid = result.get("call_sid")
        if call_sid:
            active_call_sids[call_sid] = {
                "phone": normalized_phone,
                "timestamp": time.time(),
                "status": result.get("status", "started")
            }
        return jsonify({
            "success": True,
            "status": result.get("status", "started"),
            "call_sid": call_sid,
            "phone": normalized_phone,
            "message": result.get("message", "Call initiated successfully! Your phone will ring shortly.")
        }), 200
    else:
        return jsonify({
            "success": False,
            "error": result.get("message", "Failed to initiate call. Check Twilio configuration."),
            "error_code": result.get("error_code")
        }), 400


# =============================
# CALL STATUS POLLING ENDPOINT
# =============================
@app.route("/call_status/<call_sid>", methods=["GET"])
def get_call_status(call_sid):
    """Check live status of a call via Twilio REST API for frontend feedback."""
    if call_sid.startswith("SIMULATED"):
        return jsonify({
            "call_sid": call_sid,
            "status": "completed",
            "duration": "0",
            "simulated": True
        })

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not auth_token:
        return jsonify({"call_sid": call_sid, "status": "in-progress"}), 200

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        call = client.calls(call_sid).fetch()
        return jsonify({
            "call_sid": call.sid,
            "status": call.status,
            "duration": call.duration,
            "to": call.to
        }), 200
    except Exception as exc:
        return jsonify({"call_sid": call_sid, "status": "unknown", "error": str(exc)}), 200


# =============================
# INITIAL VOICE CALL ENDPOINT
# =============================
@app.route("/voice", methods=["POST"])
def voice():
    """
    When student receives and answers the call, this is what they hear first.
    Twilio posts to this webhook upon call answer.
    """
    call_id = request.form.get("CallSid", "default")
    phone = request.form.get("From", request.form.get("To", "unknown"))

    # Store student phone number for booking
    student_phone[call_id] = phone

    call_state[call_id] = {
        "stage": "intro",
        "questions_asked": 0,
        "demo_offered": False,
        "course_selected": None,
        "demo_date": None,
        "demo_time": None,
        "student_name": None,
        "student_mobile": None
    }

    response = VoiceResponse()

    gather = Gather(
        input="speech",
        action="/process",
        method="POST",
        timeout=10,
        speechTimeout="auto",
        language="en-IN"
    )

    opening = get_intro_message()
    interest_q = get_interest_check()
    full_message = opening + " " + interest_q

    gather.say(full_message, voice="Polly.Aditi", language="en-IN")
    response.append(gather)

    return str(response)


# =============================
# MAIN PROCESSING ENDPOINT
# =============================
@app.route("/process", methods=["POST"])
def process():
    """
    MAIN ENGINE: Listens to student speech, detects questions, applies Gemini AI
    and sales intelligence, and executes course booking stages.
    """
    user_input = request.form.get("SpeechResult", "").strip()
    call_id = request.form.get("CallSid", "default")

    response = VoiceResponse()
    state = get_state(call_id)
    current_turn = get_turn(call_id)

    gather = Gather(
        input="speech",
        action="/process",
        method="POST",
        timeout=10,
        speechTimeout="auto",
        language="en-IN"
    )

    # =============================
    # HANDLE NO SPEECH
    # =============================
    if not user_input:
        response.say(
            "Sorry, I could not hear you clearly. Please repeat. Ask about course, fees, placements, or anything else.",
            voice="Polly.Aditi",
            language="en-IN"
        )
        response.append(gather)
        return str(response)

    # =============================
    # HANDLE HARD EXIT
    # =============================
    if any(word in user_input.lower() for word in ["stop calling", "don't call", "remove me", "not interested at all"]):
        response.say("Okay, no problem! All the best!", voice="Polly.Aditi", language="en-IN")
        response.hangup()
        return str(response)

    # =============================
    # TRACK THE CONVERSATION
    # =============================
    add_to_history(call_id, "Student", user_input)
    increment_turn(call_id)
    current_turn = get_turn(call_id)

    print(f"\n[Turn {current_turn}] Student: {user_input}")

    # =============================
    # INITIAL STAGE: YES/NO TO BECOME SOFTWARE ENGINEER
    # =============================
    if state["stage"] == "intro":
        if is_affirmative(user_input):
            ai_response = get_yes_response()
            state["stage"] = "course_selection"
            update_state(call_id, state)
        elif is_negative(user_input):
            closing_msg = get_no_response()
            response.say(closing_msg, voice="Polly.Aditi", language="en-IN")
            response.hangup()
            return str(response)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_interest_check() + " దయచేసి yes లేదా no చెప్పండి బ్రో."
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)

    # =============================
    # STAGE: COURSE SELECTION
    # =============================
    elif state["stage"] == "course_selection":
        course = extract_course(user_input)
        if course:
            ai_response = get_course_confirmation(course)
            state["course_selected"] = course
            state["stage"] = "demo_interest"
            update_state(call_id, state)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_course_selection()
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)

    # =============================
    # STAGE: DEMO INTEREST
    # =============================
    elif state["stage"] == "demo_interest":
        course_name = state.get("course_selected")
        if is_affirmative(user_input):
            ai_response = get_demo_booking(course_name)
            state["stage"] = "demo_date_selection"
            update_state(call_id, state)
        elif is_negative(user_input):
            ai_response = "సరే బ్రో, ఏ problem లేదు బ్రో. డిమో ఇంకా పిక్క్కు చేయాలని కంటే తర్వాత contact చేయవచ్చు బ్రో. Thanks బ్రో!"
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.hangup()
            return str(response)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_demo_booking(course_name)
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)

    # =============================
    # STAGE: DEMO DATE SELECTION
    # =============================
    elif state["stage"] == "demo_date_selection":
        demo_day = extract_day(user_input)
        if demo_day:
            ai_response = get_demo_time()
            state["demo_date"] = demo_day
            state["stage"] = "demo_time_selection"
            update_state(call_id, state)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            course_name = state["course_selected"]
            ai_response = get_demo_booking(course_name)
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)

    # =============================
    # STAGE: DEMO TIME SELECTION
    # =============================
    elif state["stage"] == "demo_time_selection":
        demo_time = extract_time(user_input)
        if demo_time:
            ai_response = f"బాగుంది బ్రో! నీకు {demo_time} time convenient బ్రో. ఇప్పుడు నీ details collect చేస్తాను బ్రో. మొదట నీ పేరు చెప్పు బ్రో?"
            state["demo_time"] = demo_time
            state["stage"] = "collect_student_details"
            update_state(call_id, state)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_demo_time()
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)

    # =============================
    # STAGE: COLLECT STUDENT DETAILS
    # =============================
    elif state["stage"] == "collect_student_details":
        if state["student_name"] is None:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            state["student_name"] = user_input.strip()
            ai_response = f"ధన్యవాదాలు {state['student_name']} బ్రో! ఇప్పుడు నీ mobile number చెప్పు బ్రో?"
            update_state(call_id, state)
        elif state["student_mobile"] is None:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            state["student_mobile"] = user_input.strip()
            course_name = state["course_selected"]
            from booking_system import get_course_info
            course_info = get_course_info(course_name)
            course_display = course_info["name"] if course_info else course_name
            ai_response = f"సరే {state['student_name']} బ్రో! నీ mobile number {state['student_mobile']} ని confirm చేస్తున్నాను బ్రో. నీ course: {course_display} బ్రో. ఇది correct ఆ బ్రో? Yes or No బ్రో?"
            update_state(call_id, state)
        else:
            # Confirming course selection
            if is_affirmative(user_input):
                course_name = state["course_selected"]
                from booking_system import get_course_info
                course_info = get_course_info(course_name)

                booking = create_booking(
                    phone_number=state["student_mobile"],
                    course_name=course_info["name"] if course_info else "Unknown",
                    demo_date=state["demo_date"],
                    demo_time=state["demo_time"],
                    student_name=state["student_name"]
                )

                ai_response = f"పర్ఫెక్ట్ బ్రో! {state['student_name']}, నీ booking confirmed బ్రో! Course: {course_info['name'] if course_info else course_name} బ్రో, Date: {state['demo_date']} బ్రో, Time: {state['demo_time']} బ్రో. ఈ details నీ mobile కి message లో కూడా పంపిస్తాం బ్రో."
                state["stage"] = "booking_complete"
                update_state(call_id, state)
            elif is_negative(user_input):
                ai_response = get_course_selection()
                state["stage"] = "course_selection"
                update_state(call_id, state)
            else:
                if try_general_question_response(response, call_id, user_input, state):
                    return str(response)
                ai_response = "సరే బ్రో, ఈ డీటెయిల్స్ confirm కావాలా? Yes లేదా No చెప్పు బ్రో."

        response.say(ai_response, voice="Polly.Aditi", language="en-IN")
        response.append(gather)
        return str(response)

    # =============================
    # STAGE: BOOKING COMPLETE
    # =============================
    elif state["stage"] == "booking_complete":
        course_name = state["course_selected"]
        from booking_system import get_course_info, get_student_booking
        booking = get_student_booking(student_phone.get(call_id, "unknown"))

        closing_msg = get_closing(booking) if booking else "Thank you!"
        response.say(closing_msg, voice="Polly.Aditi", language="en-IN")
        response.hangup()
        return str(response)

    # =============================
    # STAGE: ACTIVE (QUESTIONS & INTELLIGENCE)
    # =============================
    else:
        question_type, direct_answer = detect_question_type(user_input)

        if direct_answer:
            intro = get_answer_intro(question_type)
            actual_answer = generate_answer(question_type, user_input)
            ai_response = intro + " " + actual_answer
            print(f"[Answer Type] {question_type}")
        elif question_type != "unclear":
            ai_response = generate_answer(question_type, user_input)
            print(f"[Question Detected] {question_type}")
        else:
            # Leverage Gemini AI for complex/unclear queries with knowledge base fallback
            ai_response = generate_answer("unclear", user_input)
            print("[Gemini/Knowledge Base Fallback Invoked]")

    # =============================
    # SPEAK THE RESPONSE
    # =============================
    response.say(ai_response, voice="Polly.Aditi", language="en-IN")
    add_to_history(call_id, "Agent", ai_response)

    # =============================
    # SMART FOLLOW UP & DEMO PUSH
    # =============================
    demo_msg = get_demo_message(current_turn)

    if demo_msg and not state["demo_offered"]:
        follow_up = demo_msg
        state["demo_offered"] = True
        update_state(call_id, state)
    elif current_turn >= 8:
        follow_up = get_after_answer()
    else:
        follow_up = get_after_answer()

    gather.say(follow_up, voice="Polly.Aditi", language="en-IN")
    response.append(gather)

    print(f"[Follow-up] {follow_up}\n")
    return str(response)


# =============================
# APPLICATION ENTRYPOINT
# =============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true")

    # Automatically initialize ngrok tunnel and sync Twilio webhook if running locally
    public_url = None
    try:
        from tunnel import start_auto_tunnel
        public_url = start_auto_tunnel(port=port)
    except Exception as exc:
        public_url = None

    print(f"\n🚀 ADVANCED AI Sales Calling Agent is ready!")
    print(f"💻 Local Computer:        http://localhost:{port}/")
    if public_url:
        print(f"📱 Open on Any Mobile:    {public_url}/")
        print(f"🌐 Twilio Voice Webhook:  {public_url}/voice")
    print(f"✅ One single terminal is all you need!\n")

    app.run(host="0.0.0.0", port=port, debug=debug_mode)
