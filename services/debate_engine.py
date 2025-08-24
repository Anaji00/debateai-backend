# services/debate_engine.py
import json
import hashlib
from openai import AsyncOpenAI
from services.characterprompts import get_character_prompt
from models.debate_models import DebateSession
from services.name_map import to_canonical

from typing import List, Dict, Any, Optional

def _json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)

def _json_loads_safe(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None


class DebateEngine:
    """
    Voice-agnostic. Uses canonical names in prompts/transcript so the model
    speaks as the real character (e.g., 'Donald Trump', 'Thanos').
    """

    def __init__(self, async_client: AsyncOpenAI):
        self.async_client = async_client
        self.rag_decision_cache: Dict[str, Dict[str, str]] = {}


    async def generate_response(
        self, 
        messages: List[Dict[str, Any]],
        *,
        model: str = "gpt-4o-mini",
        temperature: float = 0.9,
        max_tokens: int = 500,
    ) -> str:

        stream = await self.async_client.chat.completions.create(
            model = model,
            messages=messages,
            temperature=temperature,
            stream=True,
            max_tokens=max_tokens,
        )
        
        full_reply: List[str] = []
        async for chunk in stream:
            delta = chunk.choices[0].delta
            token = getattr(delta, "content", None)
            if token:
                full_reply.append(token)
        return "".join(full_reply)
    
    def rag_profile_for(self, character: str) -> Dict[str, str]:
        try:
            from services.characterprompts import rag_behavior_for
            base = rag_behavior_for(character) or {}
        except Exception as e:
            base = {}

        default_mode = base.get("default_mode", "persona_paraphrase")
        cite_style = base.get("cite_style", "none")

        tactic_script = (
            "After reading the excerpts: if they SUPPORT your stance, amplify them boldly in your own voice. "
            "If they CONTRADICT your stance, spin them in-character: reframe, cast doubt, cherry-pick, or contrast with anecdotes/past wins. "
            "Stay laser-focused on the debate topic."       
        )

        return {
            "mode": default_mode,
            "cite_style": cite_style,
            "tactic_script": tactic_script,
        }
    
    async def decide_rag_mode(
        self,
        *,
        current_speaker: str,
        topic: str, 
        history: List[Dict[str, str]],
        sources: List[Dict[str, Any]],
        default_mode: str,
        cite_style: str,
    ) -> Dict[str, str]:
        if not sources:
            return {"mode": default_mode, "cite_style": cite_style}
        
        last_user = next((h.get("content", "") for h in reversed(history) if (h.get("role", "").lower() == "user" and h.get("content"))), "")
        last_assistant = next((h.get("content", "") for h in reversed(history) if (h.get("role", "").lower() == "assistant" and h.get("content"))), "")
        claim_context = (last_user or last_assistant or topic or "").strip()[:600]

        items = [
            {
                "title": s.get("title") or s.get("filename") or "Document",
                "chunk": int(s.get("chunk_index", 0)),
                "snippet": (s.get("snippet") or "")[:700]
            }
            for s in sources
        ]

        key_material = f"{current_speaker}|{topic}|{claim_context}|{_json_dumps(items)}"
        cache_key = hashlib.sha1(key_material.encode("utf-8")).hexdigest()
        cached = self.rag_decision_cache.get(cache_key)
        if cached:
            return cached


        messages = [
            {
            "role": "system",
            "content": (
               "Classify how each excerpt relates to the claim: support | contradict | unclear. "
               "Be concise and literal. Only judge what's written."

            ),
        },
        {
            "role": "user",
            "content": (
                "CLAIM:\n" + claim_context +
                "\n\nEXCERPTS (title, chunk, snippet):\n" + _json_dumps(items) +
                "\n\nReturn JSON with fields {\"support\": [idx...], \"contradict\": [idx...], \"unclear\": [idx...]}. "
                "Index uses the order of provided excerpts starting at 0."
            ),
        },  
    ]

        try:
            res = await self.async_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=150,
            )
            meta = _json_loads_safe(res.choices[0].message.content) or {}
            support_ids = set(meta.get("support", []))
            contradict_ids = set(meta.get("contradict", []))
        except Exception:
            # On failure, use persona default
            out = {"mode": default_mode, "cite_style": cite_style}
            self.rag_decision_cache[cache_key] = out
            return out
        
        has_support = any(i in support_ids for i in range(len(items)))
        has_contradict = any(i in contradict_ids for i in range(len(items)))

        if has_support and not has_contradict:
            next_mode = "persona_paraphrase" if default_mode != "evidence_cite" else "evidence_cite"
            out = {"mode": next_mode, "cite_style": cite_style}
            self.rag_decision_cache[cache_key] = out
            return out
        
        if has_contradict and not has_support:
            out = {"mode": "weaponize_spin", "cite_style": cite_style}
            self.rag_decision_cache[cache_key] = out
            return out
        
        # mixed, fall back to persona default
        out = {"mode": default_mode, "cite_style": cite_style}
        self.rag_decision_cache[cache_key] = out
        return out
            
    def generate_solo_debate(self, character: str, history: List[Dict[str, Any]], context: str = "") -> List:
        canon = to_canonical(character)
        system_prompt = get_character_prompt(canon.title())
        rules = [
            f"You are {canon.title()} in a debate with a user. Stay in character as {canon.title()}.",
            "If the last message is from the user, address it directly first in 1–2 sentences (in-character), then elaborate.",
            "Do NOT prefix your reply with any names or labels (no 'Thanos:' / 'Donald Trump:' / 'You:').",
        ]
        if context.strip():
            rules.append(f"Use this document as context for your response, use your character worldview or attack your opponent's arguments if applicable:\n{context.strip()}")


        
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt + "\n\n" + "\n".join(rules)}]
        messages += (history or [])
        return messages

    def generate_versus_debate(
        self,
        speaker: str,
        opponent: str,
        topic: str,
        history: List[Any],
        context: str = "",
        last_speaker: Optional[str] = None
    ) -> List[Dict[str, Any]]:

        spk_canon = to_canonical(speaker)
        opp_canon = to_canonical(opponent)

        norm_history: List[Dict[str, str]] = []
        if history:
            first = history[0]
            if isinstance(first, dict):
                for h in history:
                    role = h.get("role", "assistant")
                    content = (h.get("content") or "").strip()
                    if content:
                        norm_history.append({"role": role, "content": content})
            else:
                for spk, text in history:
                    text = (text or "").strip()
                    if not text:
                        continue
                    role = "user" if spk == "You" else "assistant"
                    norm_history.append({"role": role, "content": text})


        last_is_inject = bool(norm_history and norm_history[-1]["role"] == "user")



        speaker_prompt = get_character_prompt(spk_canon.title())
        rules = [
            f"You are {spk_canon.title()} debating {opp_canon.title()} on '{topic}'. Stay in character as {spk_canon.title()}.",
            f"Stay strictly in character and argue from your worldview, respond only as {spk_canon.title()}, never speak for {opp_canon.title()}.",
            "If the audience (role=user) interjects, FIRST answer the user's question clearly in 1–2 sentences to support your current stance no matter how morally or logically wrong, then rebut your opponent. Use the user's content to your advantage",
            "Do NOT prefix your reply with any labels (no 'Thanos:' / 'Donald Trump:' / 'You:'). You can still address your opponent by name.",
            "Only respond to actual 'user' turns or actual opponent content; do not invent either.",
        ]

        if context.strip():
            rules.append("Use the provided context to your advantage in the argument, even if it proves you wrong")

        system_prompt = speaker_prompt + "\n\n" + "\n".join(rules)
        

        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(norm_history)
        if last_is_inject:
            messages.append({
                "role": "system",
                "content":"Reminder, the last message is from the 'user'. Answer it first in your rebuttal then pivot to your opponent." 
        })
        return messages

        
    def create_assistant_debate_messages(self, history: List[Dict[str, Any]], context: str = "") -> List:
        system_prompt = get_character_prompt("Debate Assistant")
        rules = [
            "Reply as Devil's Advocate in sharp, adversarial style.",
            "Do NOT prefix your reply with any names or labels.",
        ]
        messages = [{"role": "system", "content": system_prompt + "\n\n" + "\n".join(rules)}]
        if context.strip():
            messages.append({"role": "system", "content": f"Use this document as context:\n{context.strip()}"} )
        messages += (history or [])
        return messages

    def build_summary_prompt(self, session: DebateSession, mode: str = "summary") -> str:
        full_text = "\n".join([f"{turn.speaker}: {turn.message}" for turn in session.turns])
        intro = f"This is a debate between {session.character_1} and {session.character_2} on the topic '{session.topic}'.\n"
        if mode == "summary":
            task = "Summarize the key arguments from both sides and conclude who made the stronger case.\n\n"
        elif mode == "grade":
            task = ("Evaluate the debate strictly on argumentative strength (logic, evidence, clarity). "
                    "Decide who made the stronger case overall.\n\n")
        elif mode == "both":
            task = ("First, summarize the key arguments from both sides.\n"
                    "Then, judge the debate solely on argumentative strength and decide who made the stronger case.\n\n")
        else:
            raise ValueError("Invalid mode. Must be 'summary', 'grade', or 'both'.")
        return intro + task + full_text
