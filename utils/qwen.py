from http import HTTPStatus
import dashscope
dashscope.api_key_file_path='/mnt/workspace/src/config/qwen_api_key_xf.txt'

class QueryTongyi:
    #return format: 
    #status: True/False
    #content:
    def chat(self, prompt):
        res = {}
        try:
            response = dashscope.Generation.call(
                model=dashscope.Generation.Models.qwen_plus,
                #model='qwen1.5-1.8b-chat',
                prompt=prompt,
                temperature=0.3,
                top_p=0.8
            )
            # The response status_code is HTTPStatus.OK indicate success,
            # otherwise indicate request is failed, you can get error code
            # and message from code and message.
        
            res['status'] = response.status_code == HTTPStatus.OK
            if res['status']:
                res['content'] = response.output.text
            else:
                res['content'] = ""
        except:
            res['status'] = False
            res['content'] = ""
        return res['content']