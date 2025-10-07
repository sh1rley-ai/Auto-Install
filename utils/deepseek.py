# Please install OpenAI SDK first: `pip3 install openai`

from openai import OpenAI

class Deepseek:
    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    
    def chat(self, prompt):
        response = self.client.chat.completions.create(
            model="deepseek-reasoner",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )

        return response.choices[0].message.content, response.choices[0].message.reasoning_content