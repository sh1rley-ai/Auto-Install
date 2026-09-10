from http import HTTPStatus

import dashscope


class QueryTongyi:
    def __init__(self, api_key):
        # Passed per call instead of mutating dashscope module globals.
        self.api_key = api_key

    def chat(self, prompt):
        """Return the generated text, or "" when the request fails."""
        try:
            response = dashscope.Generation.call(
                api_key=self.api_key,
                model=dashscope.Generation.Models.qwen_plus,
                prompt=prompt,
                temperature=0.3,
                top_p=0.8
            )
        except Exception:
            return ""

        if response.status_code != HTTPStatus.OK:
            return ""
        return response.output.text
