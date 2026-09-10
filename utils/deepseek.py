from openai import OpenAI

DEFAULT_MODEL = "deepseek-chat"


class Deepseek:
    def __init__(self, api_key, model=DEFAULT_MODEL):
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.model = model

    def chat(self, prompt):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )

        message = response.choices[0].message
        # Only deepseek-reasoner returns reasoning_content; other models yield None.
        return message.content, getattr(message, "reasoning_content", None)
