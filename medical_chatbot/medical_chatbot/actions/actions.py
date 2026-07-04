from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

# ---------------------------------------------------------------------------
# Triage configuration
# ---------------------------------------------------------------------------

EMERGENCY_INTENSITY_THRESHOLD = 8

EMERGENCY_KEYWORDS = [
    # Castellano
    "dolor en el pecho", "presion en el pecho", "no puedo respirar",
    "dificultad para respirar", "falta de aire", "me ahogo", "me asfixio",
    "ictus", "paralisis", "inconsciente", "convulsion",
    "hemorragia grave", "vomito sangre", "toso sangre", "escupo sangre",
    "perdida de vision repentina", "confusion repentina",
    "infarto", "me desmayo", "perdida de consciencia",
    # Catala
    "dolor al pit", "pressio al pit", "no puc respirar", "dificultat per respirar",
    "falta d'aire", "m'ofego", "paralisi", "inconscient",
    "convulsio", "hemorragia greu", "vomito sang", "tosseixo sang",
    "perdua de visio sobtada", "confusio sobtada", "infart", "em desmaio",
]

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """You are a medical assistant that extracts clinical information from a text written in Spanish or Catalan.
From the patient's text, extract only the fields that can be inferred with confidence.
Return ONLY a valid JSON object, with no additional text or code block markers.
If a field cannot be inferred, omit it.

Possible fields:
- appointment_reason (str): main reason for the visit
- pain_location (str): body part affected
- pain_type (str): type of pain or discomfort
- symptom_duration (str): how long the patient has had the symptoms
- symptom_evolution (str): whether symptoms are improving, worsening or staying the same. Infer also from phrases like "ha millorat", "va millorar", "mejoro", "esta mejor", "ha empeorado", "esta igual"
- pain_intensity (str): intensity from 0 to 10, only if an explicit number is mentioned
- taking_meds (bool): true if the patient mentions having taken any medication or remedy, even in the past. Infer from "vaig prendre", "me tomo", "he tomado", "he pres", "prendre"
- meds_details (str): name of the medication and whether it helped
- is_smoker (bool): true if the patient mentions smoking or using tobacco, false if explicitly denied
- allergies_details (str): known allergies to medications, food or other substances. If denied, use "no"
- chronic_conditions_details (str): chronic illnesses or relevant medical history. If denied, use "no"

Examples:
Text: "em fa mal el peu des d'ahir, vaig prendre paracetamol i va millorar, ara es un 3/10"
JSON: {"pain_location": "peu", "symptom_duration": "des d'ahir", "taking_meds": true, "meds_details": "paracetamol, va millorar", "symptom_evolution": "millora", "pain_intensity": "3"}

Text: "me duele la espalda desde hace una semana, me tome ibuprofeno pero sigue igual"
JSON: {"pain_location": "espalda", "symptom_duration": "una semana", "taking_meds": true, "meds_details": "ibuprofeno, sin mejoria", "symptom_evolution": "igual"}

Text: "tengo asma y soy alergico a la penicilina, no fumo"
JSON: {"chronic_conditions_details": "asma", "allergies_details": "penicilina", "is_smoker": false}

Patient text:
{text}

JSON:"""

TRIAGE_PROMPT = """You are a medical triage assistant. Based on the patient information below,
determine whether the patient needs IMMEDIATE emergency care (ER or 112) or can safely
wait for a regular appointment.

Answer with ONLY a JSON object with a single key "needs_emergency" (boolean).
Do not add any explanation or extra text.

Patient information:
- Reason for visit: {appointment_reason}
- Pain location: {pain_location}
- Pain type: {pain_type}
- Symptom duration: {symptom_duration}
- Symptom evolution: {symptom_evolution}
- Pain intensity (0-10): {pain_intensity}
- Current medication: {meds_details}
- Extra information: {extra_info}

JSON:"""

EDIT_PROMPT = """You are a medical assistant. The patient wants to correct or update their clinical summary.
From their message, identify which field they want to change and what the new value should be.
Return ONLY a valid JSON object with the fields to update and their new values. No additional text.

Possible fields: appointment_reason, pain_location, pain_type, symptom_duration,
symptom_evolution, pain_intensity, taking_meds (bool), meds_details,
is_smoker (text: 'si' o 'no'), allergies_details, chronic_conditions_details, has_extra_info (bool), extra_info.
IMPORTANT: is_smoker must be the string 'si' or 'no', not true/false.

Patient message:
{text}

JSON:"""

import json
import os
import urllib.request


def _call_llm(prompt: str, max_tokens: int = 512):
    """Llama a la API de Groq (capa gratuita) en lugar de Anthropic.
    Necesita la variable de entorno GROQ_API_KEY (se consigue gratis en
    https://console.groq.com/keys)."""
    try:
        payload = json.dumps({
            "model": "llama-3.3-70b-versatile",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '')}",
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _build_report(tracker) -> str:
    def val(value, fallback="—"):
        if value is None or value == "":
            return fallback
        if isinstance(value, bool):
            return "Sí" if value else "No"
        return str(value)

    def no_val(raw, no_set):
        return val(raw) if raw not in no_set else "No"

    no_meds = {"ninguno", "cap", "no", "ninguna", "Ninguno", "Cap", "No", ""}
    no_generic = {"no", "No", None, ""}
    no_extra = {"ninguna", "cap", "no", "No", "res", "ninguno", "Ninguna", ""}

    meds_raw = tracker.get_slot("meds_details")
    allergies_raw = tracker.get_slot("allergies_details")
    chronic_raw = tracker.get_slot("chronic_conditions_details")
    extra_raw = tracker.get_slot("extra_info")

    def yesno(v):
        if v is None or v == "":
            return "—"
        if isinstance(v, bool):
            return "Sí" if v else "No"
        if str(v).lower() in ("si", "sí", "yes", "true", "1"):
            return "Sí"
        if str(v).lower() in ("no", "false", "0"):
            return "No"
        return str(v)

    return (
        "📋 *Resum de la consulta / Resumen de la consulta:*\n\n"
        f"🔹 Motiu / Motivo: {val(tracker.get_slot('appointment_reason'))}\n"
        f"🔹 Localització / Localización: {val(tracker.get_slot('pain_location'))}\n"
        f"🔹 Tipus de sensació / Tipo de sensación: {val(tracker.get_slot('pain_type'))}\n"
        f"🔹 Durada / Duración: {val(tracker.get_slot('symptom_duration'))}\n"
        f"🔹 Evolució / Evolución: {val(tracker.get_slot('symptom_evolution'))}\n"
        f"🔹 Intensitat / Intensidad (0-10): {val(tracker.get_slot('pain_intensity'))}\n"
        f"🔹 Medicació / Medicación: {no_val(meds_raw, no_meds)}\n"
        f"🔹 Tabac / Tabaco: {yesno(tracker.get_slot('is_smoker'))}\n"
        f"🔹 Al·lèrgies / Alergias: {no_val(allergies_raw, no_generic)}\n"
        f"🔹 Malalties cròniques / Enfermedades crónicas: {no_val(chronic_raw, no_generic)}\n"
        f"🔹 Informació addicional / Información adicional: {no_val(extra_raw, no_extra)}\n"
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

class ActionRouteByLanguage(Action):
    """No-op action used as a routing step in greet_and_select_language.
    Returns no events; the flow's next conditions read preferred_language from the slot."""
    def name(self) -> Text:
        return "action_route_by_language"

    def run(self, dispatcher, tracker, domain):
        return []


class ActionExtractSlots(Action):
    def name(self) -> Text:
        return "action_extract_slots"

    def run(self, dispatcher, tracker, domain):
        initial_description = (
            tracker.get_slot("initial_description")
            or tracker.latest_message.get("text", "")
        )
        if not initial_description:
            return []

        raw_text = _call_llm(EXTRACT_PROMPT.replace("{text}", initial_description))
        if not raw_text:
            return []

        try:
            extracted = json.loads(raw_text)
        except Exception:
            return []

        slot_events = []
        text_slots = [
            "appointment_reason", "pain_location", "pain_type",
            "symptom_duration", "symptom_evolution", "pain_intensity",
            "meds_details", "allergies_details", "chronic_conditions_details",
        ]
        bool_slots = ["taking_meds"]
        # is_smoker is a text slot ('si'/'no') to avoid Rasa CALM falsy-skip
        text_bool_slots = ["is_smoker"]

        for slot in text_slots:
            if slot in extracted and extracted[slot] not in (None, ""):
                slot_events.append(SlotSet(slot, str(extracted[slot])))

        for slot in bool_slots:
            if slot in extracted and extracted[slot] is not None:
                slot_events.append(SlotSet(slot, bool(extracted[slot])))

        for slot in text_bool_slots:
            if slot in extracted and extracted[slot] is not None:
                slot_events.append(SlotSet(slot, "si" if extracted[slot] else "no"))

        return slot_events


class ActionTriageCheck(Action):
    def name(self) -> Text:
        return "action_triage_check"

    def run(self, dispatcher, tracker, domain):
        needs_emergency = False

        intensity = tracker.get_slot("pain_intensity")
        if intensity is not None:
            try:
                if float(intensity) >= EMERGENCY_INTENSITY_THRESHOLD:
                    needs_emergency = True
            except (ValueError, TypeError):
                pass

        if not needs_emergency:
            combined_text = " ".join([
                tracker.get_slot("appointment_reason") or "",
                tracker.get_slot("pain_location") or "",
                tracker.get_slot("pain_type") or "",
                tracker.get_slot("symptom_evolution") or "",
                tracker.get_slot("extra_info") or "",
                tracker.get_slot("initial_description") or "",
            ]).lower()
            for keyword in EMERGENCY_KEYWORDS:
                if keyword in combined_text:
                    needs_emergency = True
                    break

        if not needs_emergency:
            prompt = TRIAGE_PROMPT.format(
                appointment_reason=tracker.get_slot("appointment_reason") or "N/A",
                pain_location=tracker.get_slot("pain_location") or "N/A",
                pain_type=tracker.get_slot("pain_type") or "N/A",
                symptom_duration=tracker.get_slot("symptom_duration") or "N/A",
                symptom_evolution=tracker.get_slot("symptom_evolution") or "N/A",
                pain_intensity=tracker.get_slot("pain_intensity") or "N/A",
                meds_details=tracker.get_slot("meds_details") or "N/A",
                extra_info=tracker.get_slot("extra_info") or "N/A",
            )
            raw_text = _call_llm(prompt, max_tokens=64)
            if raw_text:
                try:
                    result = json.loads(raw_text)
                    needs_emergency = bool(result.get("needs_emergency", False))
                except Exception:
                    pass

        return [SlotSet("needs_emergency", needs_emergency)]


class ActionShowReport(Action):
    def name(self) -> Text:
        return "action_show_report"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(text=_build_report(tracker))
        return []


class ActionHandleReportEdit(Action):
    def name(self) -> Text:
        return "action_handle_report_edit"

    def run(self, dispatcher, tracker, domain):
        edit_request = tracker.get_slot("edit_request") or tracker.latest_message.get("text", "")
        raw_text = _call_llm(EDIT_PROMPT.format(text=edit_request), max_tokens=256)

        slot_events = []
        if raw_text:
            try:
                updates = json.loads(raw_text)
                text_slots = [
                    "appointment_reason", "pain_location", "pain_type",
                    "symptom_duration", "symptom_evolution", "pain_intensity",
                    "meds_details", "allergies_details", "chronic_conditions_details",
                    "extra_info",
                ]
                bool_slots = ["taking_meds", "has_extra_info"]
                text_bool_slots = ["is_smoker"]
                for slot in text_slots:
                    if slot in updates and updates[slot] not in (None, ""):
                        slot_events.append(SlotSet(slot, str(updates[slot])))
                for slot in bool_slots:
                    if slot in updates and updates[slot] is not None:
                        slot_events.append(SlotSet(slot, bool(updates[slot])))
                for slot in text_bool_slots:
                    if slot in updates and updates[slot] is not None:
                        slot_events.append(SlotSet(slot, "si" if updates[slot] else "no"))
            except Exception:
                pass

        # Reset edit_request and report_confirmed so the next collect always asks
        slot_events.append(SlotSet("edit_request", None))
        slot_events.append(SlotSet("report_confirmed", None))

        # Build an updated tracker-like snapshot to show the corrected report.
        # We apply the slot updates manually so the report reflects the new values.
        updated_slots = {e.key: e.value for e in slot_events if hasattr(e, "key")}

        class _PatchedTracker:
            def __init__(self, base_tracker, overrides):
                self._base = base_tracker
                self._overrides = overrides
            def get_slot(self, key):
                if key in self._overrides:
                    return self._overrides[key]
                return self._base.get_slot(key)

        patched = _PatchedTracker(tracker, updated_slots)
        dispatcher.utter_message(text=_build_report(patched))

        return slot_events


class ActionBookAppointment(Action):
    def name(self) -> Text:
        return "action_book_appointment"

    def run(self, dispatcher, tracker, domain):
        return []


class ActionRecommendationsEs(Action):
    def name(self):
        return "action_recommendations_es"

    def run(self, dispatcher, tracker, domain):
        prompt = f"""Eres el asistente virtual de La Meva Salut. Responde ÚNICAMENTE en castellano.
Basándote en la información del paciente, ofrece entre 3 y 5 recomendaciones breves para antes de la cita.
No diagnostiques. Sé conciso y directo.

Información del paciente:
- Motivo: {tracker.get_slot('appointment_reason') or 'No especificado'}
- Localización: {tracker.get_slot('pain_location') or 'No especificada'}
- Tipo de dolor: {tracker.get_slot('pain_type') or 'No especificado'}
- Duración: {tracker.get_slot('symptom_duration') or 'No especificada'}
- Evolución: {tracker.get_slot('symptom_evolution') or 'No especificada'}
- Intensidad: {tracker.get_slot('pain_intensity') or 'No especificada'}/10
- Medicación: {tracker.get_slot('meds_details') or 'Ninguna'}
- Alergias: {tracker.get_slot('allergies_details') or 'Ninguna'}
- Enfermedades crónicas: {tracker.get_slot('chronic_conditions_details') or 'Ninguna'}

Exemples:
- hidrátate.
- no hagas esfuerzos.
- haz una lista de las dudas que tengas para tu médico.
- recuerda presentarte a la analítica en ayunas.
- descansa hasta la cita.
- haz un seguimiento de tus síntomas para presentárselo a tu médico.
- pide ayuda a alguien hasta el día de la cita.
- ven a la cita acompañado.

Respuesta:"""

        response = _call_llm(prompt, max_tokens=512)
        dispatcher.utter_message(text=response or "Descansa, mantente hidratado y evita esfuerzos hasta la cita.")
        dispatcher.utter_message(text="Hasta pronto! Que te mejores pronto.")
        return []


class ActionRecommendationsCa(Action):
    def name(self):
        return "action_recommendations_ca"

    def run(self, dispatcher, tracker, domain):
        prompt = f"""Ets l'assistent virtual de La Meva Salut. Respon ÚNICAMENT en català.
Basant-te en la informació del pacient, ofereix entre 3 i 5 recomanacions breus per abans de la cita.
No diagnostiquis. Sigues concís i directe.

Informació del pacient:
- Motiu: {tracker.get_slot('appointment_reason') or 'No especificat'}
- Localització: {tracker.get_slot('pain_location') or 'No especificada'}
- Tipus de dolor: {tracker.get_slot('pain_type') or 'No especificat'}
- Duració: {tracker.get_slot('symptom_duration') or 'No especificada'}
- Evolució: {tracker.get_slot('symptom_evolution') or 'No especificada'}
- Intensitat: {tracker.get_slot('pain_intensity') or 'No especificada'}/10
- Medicació: {tracker.get_slot('meds_details') or 'Cap'}
- Al·lèrgies: {tracker.get_slot('allergies_details') or 'Cap'}
- Malalties cròniques: {tracker.get_slot('chronic_conditions_details') or 'Cap'}

Exemples:
- hidrata't.
- no facis esforços.
- fes una llista dels dubtes que tinguis pel metge / la metgessa.
- recorda presentar-te a la anàlisi sense haver menjat abans.
- descansa fins la cita.
- fes un seguiment dels teus símptomes per presentar-lo al metge / la metgessa.
- demana a algú que t'ajudi fins el dia de la cita.
- vine a la cita acompanyat.

Resposta:"""

        response = _call_llm(prompt, max_tokens=512)
        dispatcher.utter_message(text=response or "Descansa, hidrata't i evita esforços fins a la cita.")
        dispatcher.utter_message(text="Fins aviat! Que et milloris.")
        return []
