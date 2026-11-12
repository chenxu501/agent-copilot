# qwen_model_prompts.py —— 【只在换 qwen 模型时看】qwen 专用提示词子类，继承 general_prompts.py 的 PromptModelHub

# 引入 general_prompts.py 的基类 PromptModelHub，下面继承它（≈ import + extends）
from prompt import PromptModelHub
# 引入项目自封装日志工具，打印"正在用哪套提示词"（≈ slf4j）
from utils import logger


# 千问模型的提示词中心：只覆盖 qwen 不同的话术，其余复用基类（≈ 子类重写 @Override）
class QwenModelPromptHub(PromptModelHub):

    # 构造方法：保存系统级提示词和模型名（≈ Java 构造方法）
    def __init__(self, system_prompt,model_name):
        # 保存系统级提示词（self ≈ this）
        self.system_prompt = system_prompt
        # 停止标签：无结果时返回它（None ≈ null）
        self.stop_label = None
        # 拼一句日志前缀，标明当前用的模型（f-string ≈ String.format）
        self.use_desc = f"使用{model_name}模型提示词===>"

    # 重写基类方法：qwen 版"判断单/多 API 任务"话术，比基类多了"原子查询通常是单工具任务"等细化规则
    def get_root_task_prompt_text(self):
        # 打日志：正在使用千问模型的提示词
        logger.info(self.use_desc)
        # 话术：让 AI 判断用户请求是单 API 任务还是多 API 任务，多步则给出第一个子任务（文字勿改动）
        return """
        You are an excellent API tool planning expert, and I will provide you with user requests and a list of tools.. 
        Please determine whether to complete the request as a multi API tool task based on user requests and tool list, which requires calling multiple APIs, or as a single API tool task that only requires calling a single API.  
        If it is a single API tool task, please answer 'yes'; If it is a multi API tool task, please answer 'no' and provide the first subtask request statement described in natural language to find the corresponding API.
        Please note that usually, atomic information query is a single-tool task.
        Usually, querying information about a single product, order, or logistics supplier is a single-tool task
        Creating a single order and adding a single product are tasks that can be completed using a single tool.
        
        The tool list is as follows:[
        {tool_descs}
        ]        
        
        The reply format is as follows:
        Single API tool task: Yes/No
        First subtask description: A subtask described in natural language to find the corresponding API
        
        Example1:
        User Request: 先分别查询苹果和梨子的产品信息，再分别查询产品ID为3的产品信息
        
        Example1 Output:
        Single API tool task: No
        First subtask description: 查询苹果的产品信息
        
        User Request: {query}
        Please output the answer directly, do not output the thought process!
        """

    # 重写基类方法：qwen 版"缺参数补充查询"话术，带 Few-Shot 示例教 AI 怎么编补充查询
    def get_param_task_prompt_text(self):
        # 打日志：正在使用千问模型的提示词
        logger.info(self.use_desc)
        # 话术：让 AI 为缺失参数编一句自然语言查询，如"请查询能配送南京的物流供应商信息"（文字勿改动）
        return """
        You are an excellent API tool invocation master. I will provide you with the extraction status of the original request and the current API request parameters.    
        Please generate a natural language description of the query subtask for the missing parameters. The extracted parameters and parameter values should not appear in the statement, and the statement should include necessary query conditions to find the appropriate API
        
        Please follow the following rules:
        1. The generated query subtask should be described according to the information of XX in the XX query.For example, when there is a lack of information about the logistics supplier ID, please generate "请查询XXX的物流供应商信息" according to the user's request, where XXX generates a targeted attributive based on the user's request.
        
        Example1:
        
        Original request:  创建一个产品ID为21，数量为109，配送区域为南京的订单
        Current parameter extraction: 
            "quantity": 109,
            "supplierId": "",
            "productId": 21,
            "orderRegion": "南京"
            
        Missing parameters: supplierId: 物流供应商Id
        
        Example1 output:
        请查询能够配送南京的物流供应商信息
        
        
        Now I will give you the problem to be solved. Please solve it according to the example and rules
        
        Original request: {query}
        Current parameter extraction: {params}
        Missing parameters: {missing_param}
        
        Please output natural language description query statement directly, no need to output the thought process.
            """

    # 重写基类方法：qwen 版"多步任务推进"话术，多了"子任务无依赖、查询结果为空也算完成"等规则
    def gen_subtask_context_prompt(self, query, context):
        # 打日志：正在使用千问模型的提示词
        logger.info(self.use_desc)
        # 话术：让 AI 根据已调用 API 的记录判断任务是否完成，未完成则给下一个子任务（文字勿改动）
        REACT_PROMPT = """
        You are an outstanding expert in API tool planning, and I will provide a user request that may require calling multiple APIs to complete. 
        At the same time, I will also provide contextual information about the API that has been called so far. 
        Please determine whether the request has been completed based on the existing context. 
        If completed, please reply with 'Yes'; If not completed, please reply with 'No' and provide the next subtask request statement described in natural language to find the corresponding API.
        
        Please note that if a suitable API is selected for a subtask and the API call returns normally, even if the API call result indicates that the query result does not exist, such as returning an empty list '[]' or returning that the information does not exist, the task should still be considered completed, and the completion result should be considered that the information does not exist or is empty.
        Please note that there is no dependency relationship between different subtasks, that is, the content of the API output of the previous subtask is independent of the content of the next subtask
        
        The reply format is as follows:
        Has the task been completed: Yes/No
        The Next Subtask Request: the next subtask request statement described in natural language to find the corresponding API.
        
        
        
        Now I will give you the problem to be solved. Please solve it according to the example and rules
        
        
        User Request: {query}
        
        API Context:
        {context}       
        
        
        Please output the answer directly, do not output the thought process! 
        """
        # 话术模板：单条"已调用 API 上下文"的拼接格式（子任务描述 + API 描述 + 返回结果）
        API_CONTEXT_DESC = """
        SubTask{index}: {task_description}
        API{index}: {api_description}
        API{index} Response: {api_response}        
        """

        # 用户请求为空直接返回停止标签
        if len(query) == 0:
            # 返回停止标签（≈ null）
            return self.stop_label

        # 子任务编号，仅用于提示词里的编号展示
        index = 1
        # 累积"已调用 API 上下文"文本（字符串 += 拼接 ≈ StringBuilder）
        apis = ""
        # 遍历已调用 API 记录（context 是 list[dict]，每项含 tool/result/task_description）
        for tmp in context:
            # 按模板拼一段上下文（.format ≈ String.format）
            api = API_CONTEXT_DESC.format(index=str(index), api_description=tmp["tool"],
                                    api_response=tmp["result"], task_description=tmp["task_description"])
            # 把这段上下文追加进总文本
            apis += api
            # 编号 +1
            index += 1

        # 把用户请求和上下文填进提示词模板
        prompt = REACT_PROMPT.format(query=query, context=apis)
        # 打印调试日志
        logger.debug(f"[{query}]子任务上下文提示词: {prompt}")
        # 返回拼好的提示词
        return prompt


    # 重写基类方法：qwen 版"参数提取"话术，多了"产品名不带'产品'二字"等细化规则
    def get_all_parameters_prompt_text(self):
        # 打日志：正在使用千问模型的提示词
        logger.info(self.use_desc)
        # 话术：让 AI 从用户问题中按参数定义抽值输出 JSON，禁止翻译语言（文字勿改动）
        return '''Answer the following questions as best you can.

        Extract the arguments: {arguments} 
        Format the arguments as a JSON object
        You must obey: the key of the JSON must be exactly the same as the argument name I gave it (must follow the original format)
        You must obey: the extracted arguments be words that appear in the original text of the question
        You must obey: When extracting the product name parameter, there is no need to include the word "产品"
        You must obey: if the format of param is "date-time",please follow the example "2025-08-12T13:58:04.094Z"
        You must obey: if the format of param is "enum"， Please select one from the enum list as the parameter value
        
        Use the following format:
        {output}
        Question:{query}
        The execution results of the predecessor tasks is : {predecessor_tasks}
        '''
