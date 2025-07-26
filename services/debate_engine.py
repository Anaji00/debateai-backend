# Import the OpenAI client for making API calls and the character prompt utility.
from openai import OpenAI
from services.characterprompts import get_character_prompt
from models.debate_models import DebateSession, DebateTurn
 
class DebateEngine:
    """
    Encapsulates the logic for generating debate responses using an AI model.

    This class is responsible for constructing appropriate prompts based on the
    debate format (solo, versus) and interacting with the provided AI client
    to get character responses.
    """
    def __init__(self, client: OpenAI):
        """
        Initializes the DebateEngine with an OpenAI client.

        Args:
            client (OpenAI): An instance of the OpenAI client.
        """
        self.client = client
 
    def generate_response(self, messages):
        """
        Sends a list of messages to the AI model and returns the generated content.

        Args:
            messages (list): A list of message dictionaries conforming to the
                             OpenAI API format.

        Returns:
            str: The text content of the AI's response.
        """
        # Call the chat completions endpoint of the OpenAI API.
        response = self.client.chat.completions.create(
            model="gpt-4o", # Specifies the model to use.
            messages=messages, # The conversation history and prompts.
            temperature=0.9, # Controls the randomness of the output. Higher is more creative.
            max_tokens=500 # Limits the length of the generated response.
        )
        # Extract and return the text content from the first choice in the API response.
        return response.choices[0].message.content
 
    def generate_solo_debate(self, character: str, history: list, context: str = ""):
        """
        Prepares the list of messages for a solo debate (one character vs. user).

        Args:
            character (str): The name of the AI character.
            history (list): The conversation history.
            context (str, optional): Additional context for the character. Defaults to "".

        Returns:
            list: A list of message dictionaries ready to be sent to the AI model.
        """
        # Retrieve the detailed system prompt for the specified character.
        system_prompt = get_character_prompt(character)
        # Start the message list with the character's system prompt.
        messages = [{"role": "system", "content": system_prompt}]
        # If any additional context is provided, add it as another system message.
        if context.strip():
            messages.append({"role":"system", "content": f"Use the following background to support your argument:\n{context.strip()}"})
        # Append the existing conversation history to the message list.
        messages += history
        # Return the fully constructed list of messages, ready to be sent to the API.
        return messages
    
    def generate_versus_debate(self, speaker: str, opponent: str, topic: str, history: list, context: str = "") -> list:
        """
        Prepares the list of messages for a versus debate (two characters debating).

        Args:
            speaker (str): The character whose turn it is to speak.
            opponent (str): The opposing character.
            topic (str): The debate topic.
            history (list): The conversation history.
            context (str, optional): Additional context for the debate. Defaults to "".

        Returns:
            list: A list of message dictionaries ready to be sent to the AI model.
        """
        # Get the system prompt for the character who is currently speaking.
        speaker_prompt = get_character_prompt(speaker)
        
        # Create a single, clear system prompt that defines the character's persona and the debate context.
        # This avoids redundant or conflicting instructions for the AI model.
        base_prompt = (
            f"{speaker_prompt}\n\n"
            f"You are in a debate. Your name is {speaker}. "
            f"You are debating against {opponent} on the topic: '{topic}'.\n\n"
            "You must stay in character and respond directly to the arguments made by your opponent in the conversation that follows."
        )
        # Start the message list with this single, comprehensive system prompt.
        messages = [{"role": "system", "content": base_prompt}]

    def create_assistant_debate_messages(self, history: list, context: str = "") -> list:
        """
        Devil’s Advocate — AI challenges user.
        """
        system_prompt = get_character_prompt("Debate Assistant")
        messages = [{"role": "system", "content": system_prompt}]

        if context:
            messages.append({"role": "system", "content": f"Use this document as context:\n{context}"})

        messages += history
        return messages


        # If any additional context is provided, add it as a supporting system message.
        if context.strip():
            messages.append({"role": "system", "content": f"Use the following background to support your argument:\n{context.strip()}"})
 
        # Append the previous turns of the debate to the message list.
        # This filters out any messages from "You" to keep the context focused on the two debaters.
        messages += [{"role": "user", "content": t} for s, t in history if s!= "You"]
        # Return the fully constructed list of messages.
        return messages
    
    def build_summary_prompt(self, session: DebateSession, mode: str = "summary") -> str:
        """
        Constructs a prompt to ask the AI to summarize or grade a debate session.

        Args:
            session (DebateSession): The SQLAlchemy session object containing the debate turns.
            mode (str, optional): The type of analysis requested. Can be 'summary',
                                  'grade', or 'both'. Defaults to "summary".

        Raises:
            ValueError: If an invalid mode is provided.

        Returns:
            str: The fully constructed prompt string.
        """
        full_text = "\n".join([f"{turn.speaker}: {turn.message}" for turn in session.turns])
        intro = (
            f"This is a debate between {session.character_1} and {session.character_2} "
            f"on the topic '{session.topic}'.\n"
        )

        if mode == "summary":
            task = "Summarize the key arguments from both sides and conclude who made the stronger case.\n\n"
        elif mode == "grade":
            task = (
                "Evaluate the debate **strictly** based on argumentative strength (logic, evidence, clarity), "
                "not emotional appeal or morals. Decide who made the stronger case overall.\n\n"
        )
        elif mode == "both":
            task = (
                "First, summarize the key arguments from both sides.\n"
                "Then, judge the debate solely based on argumentative strength — "
                "not emotion or morality — and decide who made the stronger case.\n\n"
        )
        else:
            raise ValueError("Invalid mode. Must be 'summary', 'grade', or 'both'.")

        return intro + task + full_text