# api_planning_hub.py —— AI 任务规划核心：拆任务→选工具→提参数→调接口→总结→生成流程图节点

# 标准库：JSON 序列化，把参数/结果 dict 转成字符串存库（≈ Jackson 的 ObjectMapper）
import json

# 导入 apis/api_selection_hub.py 的 ApiSelectionHub，负责从候选工具里挑出本次要用的 API 工具
from apis.api_selection_hub import ApiSelectionHub
# 导入 models/llm.py 的 LargeLanguageModel，调用大模型的 HTTP 客户端封装
from models import LargeLanguageModel
# 导入 param_extraction/param_extraction_hub.py 的 ParamExtractionHub，用 LLM 从用户话里抠接口参数
from param_extraction.param_extraction_hub import ParamExtractionHub
# 导入 tasks 包的 TaskManager（写 MongoDB 任务）和 GenerateTaskHub（LLM 拆任务/生成查询）
from tasks import TaskManager,GenerateTaskHub
# 导入 tools 包的 ToolSummaryHub（LLM 总结调用结果）和 ToolUseHub（真正发 HTTP 调接口）
from tools import ToolSummaryHub, ToolUseHub
# 导入 utils 包的日志对象和常量（错误码/成功码/结果长度限制），行尾 "\" 是换行续行符
from utils import logger, TASK_ERROR_CODE, TASK_SUCCESS_CODE, RESPONSE_STATUS_CODE_SUCCESS, api_result_max_length, \
    api_result_max_threshold
# 标准库：异常堆栈格式化，出错时把调用栈写进日志（≈ e.printStackTrace()）
import traceback


# 任务编排总指挥：组合选工具/提参数/调接口/总结/存库各组件统一调度（≈ Spring 编排 Service + 依赖注入）
class ApiPlanningHub:

    # 构造方法：创建并持有各协作组件实例，后面全流程都靠它们干活（__init__ ≈ 构造方法，self ≈ this）
    def __init__(self, milvus_uri, model_path, milvus_db_name, model, temperature, top_p,
                mongo_host, mongo_db, mongo_port, topK, api_url, api_key):
        # 创建 apis/api_selection_hub.py 的 ApiSelectionHub 并持有，后面用它选 API 工具
        self.apiSelectionHub = ApiSelectionHub(milvus_uri, model_path, milvus_db_name, model, temperature, top_p,
                                                mongo_host, mongo_db, mongo_port, api_url, api_key)
        # 保存向量检索召回工具的数量 topK，选工具时使用
        self.topK = topK
        # 创建 param_extraction/param_extraction_hub.py 的 ParamExtractionHub 并持有，后面用它提取接口参数
        self.paramExtractionHub = ParamExtractionHub(model, temperature, top_p, api_url, api_key)
        # 创建 tools 包的 ToolSummaryHub 并持有，后面用它对调用链做 LLM 总结
        self.toolSummaryHub = ToolSummaryHub(model, temperature, top_p, api_url, api_key)
        # 创建 tools 包的 ToolUseHub 并持有，后面用它真正发 HTTP 请求调用目标接口
        self.toolUseHub = ToolUseHub("")
        # 创建 tasks/generate_task_hub.py 的 GenerateTaskHub 并持有，后面用它拆任务/补参查询/安全校验
        self.generateTaskHub = GenerateTaskHub(model, temperature, top_p, api_url, api_key, mongo_host, mongo_db, mongo_port, milvus_uri, milvus_db_name)
        # 创建 tasks/task_manager.py 的 TaskManager 并持有，后面用它把任务进度写回 MongoDB
        self.taskManager = TaskManager(mongo_host, mongo_db, mongo_port)
        # 创建 models/llm.py 的 LargeLanguageModel 并持有，本类直接调 LLM 时使用
        self.llm = LargeLanguageModel(api_url, api_key)
        # 保存模型名，调 LLM 时透传
        self.model = model
        # 保存采样温度，控制生成随机性
        self.temperature = temperature
        # 保存核采样概率 top_p，控制生成多样性
        self.top_p = top_p

    # 方法：让 LLM 把一段文本润色成通顺的话并返回
    def generate_output(self, text):
        # 拼出"润色"提示词，把原文接在指令后面（"+" 是字符串拼接）
        prompt = " 请将以下句子进行润色成通顺的话，请直接输出结果：\n\n\n" + text
        # 控制台打印提示词，方便调试（≈ System.out.println）
        print(prompt)
        # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让大模型执行润色改写
        result = self.llm.chat_completions(prompt, self.model, self.temperature, self.top_p)
        # 返回润色后的文本
        return result

    # 方法：把一次任务的 API 调用链转成前端流程图的"节点+边"，写入 MongoDB（≈ 组装视图模型后 save）
    def convert_inter_result(self, task_id, results, model_output, isEnd):
        # 初始化流程图主节点列表（list ≈ ArrayList）
        nodes = []
        # 初始化"缺参反向补参"子节点列表
        sub_nodes = []
        # 初始化流程图连线（边）列表
        edges = []
        # 主节点编号从 1 开始
        index = 1
        # 子节点编号从 10000 开始，避免和主节点 id 撞车
        sub_index = 10000
        # 默认调用链状态文案为"正常调用链"
        isSuccess = "正常调用链"
        # 若 LLM 判定需求无法由现有 API 实现，直接写空图入库后返回
        if model_output == "当前API无法实现用户需求":
            # 调用 tasks/task_manager.py 的 TaskManager.update_task()，把空节点空边和结论写入 MongoDB
            self.taskManager.update_task(task_id, [], [], model_output, "异常调用链", isEnd)
            # 直接结束，不再生成节点
            return
        # 遍历每一次 API 调用结果，每次调用生成一个流程图主节点
        for tmp in results:
            # 只要有一步返回码不是成功码，整条链就标记为异常调用链
            if tmp["code"] != TASK_SUCCESS_CODE:
                # 改写链状态文案为异常
                isSuccess = "异常调用链"
            # 把本次 API 调用组装成主节点，params/result 用 json.dumps（标准库）转 JSON 字符串存图
            nodes.append({
                "id": str(index),
                "name": str(index) + "_" + tmp["tool"],
                "label": tmp["tool"],
                "group": tmp["tool"],
                "task_description": tmp["query"],
                "params": json.dumps(tmp["param"], ensure_ascii=False),
                "result": json.dumps(tmp["result"], ensure_ascii=False),
            })
            # 遍历这次调用里"为补参数而额外调用的 API"记录，每条生成一个补参子节点
            for tmptmp in tmp["missing_param"]:
                # 把补参调用组装成子节点并加入子节点列表
                sub_nodes.append({
                    "id": str(sub_index),
                    "name": str(sub_index) + "_" + tmptmp["tool"],
                    "label": tmptmp["tool"],
                    "group": tmptmp["tool"],
                    "task_description": tmptmp["task_description"],
                    "params": json.dumps(tmp["param"], ensure_ascii=False),
                    "result": json.dumps(tmp["result"], ensure_ascii=False),
                })
                # 加一条"补参子节点 -> 父节点"的边，标注为缺省参数逆向API规划
                edges.append(
                    {
                        "source": str(sub_index), "target": str(index), "value": '缺省参数逆向API规划', "symbolSize": [5, 20],
                        "label": {"show": False}
                    }
                )
                # 子节点编号 +1
                sub_index += 1
            # 主节点编号 +1
            index += 1
        # 只有一个主节点时没有先后顺序可连，把子节点并入后直接写库返回
        if len(nodes) == 1:
            # 主节点和补参子节点合并成完整节点列表
            nodes = nodes + sub_nodes
            # 调用 tasks/task_manager.py 的 TaskManager.update_task()，把图数据写入 MongoDB
            self.taskManager.update_task(task_id, nodes, edges, model_output, "正常调用链路", isEnd)
            # 写库后结束方法
            return
        # 多个主节点：按执行顺序两两连"正向API规划"的边
        for i in range(len(nodes) - 1):
            # 加一条 i -> i+1 的顺序边
            edges.append(
                {
                    "source": nodes[i]["id"], "target": nodes[i + 1]["id"], "value": '正向API规划', "symbolSize": [5, 20],
                    "label": {"show": False}
                }
            )
        # 把补参子节点并入节点列表
        nodes = nodes + sub_nodes
        # 调用 tasks/task_manager.py 的 TaskManager.update_task()，把最终图数据落库（≈ repository.save()）
        self.taskManager.update_task(task_id, nodes, edges, model_output, isSuccess, isEnd)
        # 方法结束，无返回值（≈ void）
        return

    # 方法：检测 API 调用链是否死循环（同一 API 连续 3 次结果相同即判定循环），返回 True=正常
    def loop_validate(self, api_chains):
        # 记录当前正在统计的 API 名称
        current_api_name = ""
        # 记录同一 API 且结果相同的连续出现次数
        number = 0
        # 遍历调用链里的每次调用结果
        for i in range(len(api_chains)):
            # 取出第 i 次调用结果
            api_response = api_chains[i]
            # 换了 API 就重置统计（≈ switch 到新分支）
            if api_response["tool"] != current_api_name:
                # 更新当前统计的 API 名称
                current_api_name = api_response["tool"]
                # 计数重置为 1
                number = 1
            else:
                # 同一 API 且结果和上一次一模一样，计数累加
                if api_chains[i - 1]["result"] == api_response["result"]:
                    # 连续相同次数 +1
                    number += 1
                # 连续 3 次同 API 同结果，判定为循环调用
                if number == 3:
                    # 返回 False 表示发现死循环，调用方应中止任务
                    return False
        # 没检测到死循环，返回 True（≈ return true）
        return True

    # 方法：缺参数时另找一个 API 把缺失参数的值查回来（反向补参），返回 (参数值, 工具名, 补参调用记录)
    def supplement_parameters(self, new_query, missing_param):
        # 调用 apis/api_selection_hub.py 的 ApiSelectionHub.get_tool_coarse_and_fine()，为补参查询选出一个 API 工具
        tool = self.apiSelectionHub.get_tool_coarse_and_fine(new_query, None, topK=self.topK)
        # 选不到工具就补参失败
        if tool is None:
            # 返回 3 个 None（元组多返回值，≈ 返回一个小 DTO）
            return None, None, None
        # 调用 param_extraction/param_extraction_hub.py 的 ParamExtractionHub.extraction_params()，从补参查询里提取参数
        params, new_missing_param = self.paramExtractionHub.extraction_params(new_query, tool)
        # 补参调用自己还缺参数，认为补参失败
        if len(new_missing_param) != 0:
            # 返回 3 个 None 表示失败
            return None, None, None

        # 调用 tools/tool_use_hub.py 的 ToolUseHub.tool_use()，真正发 HTTP 请求调用补参 API
        single_tool_response = self.toolUseHub.tool_use(tool, params)

        # HTTP 状态码不是成功码，补参失败
        if single_tool_response.status_code != RESPONSE_STATUS_CODE_SUCCESS:
            # 返回 3 个 None
            return None, None, None

        # 响应体非空才继续解析（text ≈ ResponseBody 的字符串内容）
        if len(single_tool_response.text) != 0:
            # 标准库 json：把响应 JSON 字符串解析成 Python 对象（≈ Jackson readValue）
            results = json.loads(single_tool_response.text)

            # 底层实现，不用看：返回是数组就取第一条；isinstance ≈ instanceof
            if isinstance(results, list) and len(results) != 0:
                # 数组取第一个元素作为结果对象
                results = results[0]
            # 返回结果里正好包含要补的那个参数名，补参成功
            if missing_param in results:
                # 返回参数值、工具名和本次补参调用记录（供前端画反向补参子节点）
                return results[missing_param], tool.name_for_human, {
                    "code": TASK_SUCCESS_CODE,
                    "tool": tool.name_for_human,
                    "result": single_tool_response.text,
                    "param": params,
                    "query": new_query,
                    "task_description": new_query
                }
            else:
                # 结果里没有目标参数，补参失败
                return None, None, None
        else:
            # 响应体为空，补参失败
            return None, None, None



    # 方法：单 API 规划——选工具→提参数→（缺参则补参）→安全校验→调接口，返回本次调用的结果字典
    def single_api_planning(self, query, raw_query="", api_chains=None):
        # 打调试日志：开始单 API 检索
        logger.debug(f"[{query}]开始单API检索....")
        # 调用 apis/api_selection_hub.py 的 ApiSelectionHub.get_tool_coarse_and_fine()，第一步选出要用的 API 工具
        tool = self.apiSelectionHub.get_tool_coarse_and_fine(query, None, topK=self.topK)

        # 没找到合适工具：返回"异常调用节点"结果字典
        if tool is None:
            # 组装失败结果，code 用错误码，task_description 说明失败原因
            return {
                "code": TASK_ERROR_CODE,
                "result": "",
                "tool": "异常调用节点-无法寻找到合适的API工具",
                "missing_param": [],
                "param": {},
                "query": query,
                "task_description": "无法寻找到合适的API工具"
            }
        else:
            # 第二步：调用 param_extraction/param_extraction_hub.py 的 ParamExtractionHub.extraction_params()，LLM 抽参数并找出缺失参数
            params, missing_params = self.paramExtractionHub.extraction_params(query + " " + raw_query, tool,api_chains)
            # 打调试日志：记录参数提取结果
            logger.debug(f"参数提取[{query + ' ' + raw_query}]结果：params:{params}，missing_params：{missing_params}")
            # 浅拷贝一份参数备用（≈ new HashMap<>(params)）
            new_params = params.copy()
            # 分支一：参数齐全，直接走"安全校验→调用工具"
            if len(missing_params) == 0:
                # 打调试日志：参数无缺失直接调用
                logger.debug(f"[{query}]未缺失参数，直接工具调用")
                # 调用 tasks/generate_task_hub.py 的 GenerateTaskHub.gen_judge_task()，做提示注入攻击安全校验
                inject_flag, reason = self.generateTaskHub.gen_judge_task(query, tool, new_params)
                # 命中注入攻击：直接返回异常节点，不调外部系统
                if inject_flag:
                    # 组装"提示注入攻击"异常结果
                    return {
                        "code": TASK_ERROR_CODE,
                        "result": "inject",
                        "tool": "异常调用节点-提示注入攻击",
                        "missing_param": [],
                        "param": {},
                        "query": query,
                        "task_description": reason
                    }
                # 调用 tools/tool_use_hub.py 的 ToolUseHub.tool_use()，真实发 HTTP 请求调外部系统接口（≈ RestTemplate）
                single_tool_response = self.toolUseHub.tool_use(tool, new_params)
                # HTTP 调用失败：返回"调用外部系统失败"异常节点
                if single_tool_response.status_code != RESPONSE_STATUS_CODE_SUCCESS:
                    # 组装调用失败结果
                    return {
                        "code": TASK_ERROR_CODE,
                        "result": "",
                        "tool": "异常调用节点-调用外部系统失败",
                        "missing_param": [],
                        "param": {},
                        "query": query,
                        "task_description": "调用外部系统失败"
                    }
                # 调用成功：返回正常节点结果
                return {
                    "code": TASK_SUCCESS_CODE,
                    "tool": tool.name_for_human,
                    "result": single_tool_response.text,
                    "missing_param": [],
                    "param": params,
                    "query": query,
                    "task_description": query
                }
            else:
                # 打调试日志：进入缺参补齐流程
                logger.debug(f"[{query}]缺失参数，进行参数的补齐....")
                # 初始化补参记录列表，收集补参时额外调用的 API（供前端画反向补参链）
                missing_params_supplemented = []
                # 逐个补齐缺失参数
                for missing_param in missing_params:
                    # 调用 tasks/generate_task_hub.py 的 GenerateTaskHub.gen_param_task()，让 LLM 生成"去查这个参数"的新查询
                    gen_param_query = self.generateTaskHub.gen_param_task(query,
                                                                    json.dumps(params, ensure_ascii=False, indent=4),
                                                                    f'{missing_param.name}: {missing_param.description}')
                    # 打调试日志：记录生成的补参查询词
                    logger.debug(f"[{query}]参数生成或补齐任务的描述词为：{gen_param_query}")
                    # 调用本类 supplement_parameters()，另找 API 把缺失参数的值查回来
                    supplement_param, supplement_param_tool, supplement_param_result = self.supplement_parameters(
                        gen_param_query, missing_param.name)
                    # 补参成功：把值填回参数表并记录补参调用
                    if supplement_param is not None:
                        # 打调试日志：记录补齐的参数和补参调用信息
                        logger.debug(f"[{query}]的参数{supplement_param}已补齐：\n{supplement_param_tool}\n{supplement_param_result}")
                        # 把查到的参数值写回参数字典
                        params[missing_param.name] = supplement_param
                        # 记录这次补参调用结果，用于画反向补参子节点
                        missing_params_supplemented.append(supplement_param_result)
                    else:
                        # 补参失败：整个任务失败，返回"缺少必要参数"异常节点
                        return {
                            "code": TASK_ERROR_CODE,
                            "result": "missing_param",
                            "tool": "异常调用节点-缺少必要参数",
                            "missing_param": [],
                            "param": {},
                            "query": query,
                            "task_description": f"通过参数补全Query:{gen_param_query} 无法为 {tool.name_for_human} API 补全缺少参数 {missing_param.name}"
                        }

                # 参数补齐后再做一次提示注入攻击安全校验
                inject_flag, reason = self.generateTaskHub.gen_judge_task(query, tool, params)
                # 命中注入攻击：返回异常节点
                if inject_flag:
                    # 组装"提示注入攻击"异常结果
                    return {
                        "code": TASK_ERROR_CODE,
                        "result": "inject",
                        "tool": "异常调用节点-提示注入攻击",
                        "missing_param": [],
                        "param": {},
                        "query": query,
                        "task_description": reason
                    }

                # 打调试日志：准备用补齐的参数调用工具
                logger.debug(f"[{query}]准备进行工具{tool.operationId}调用,参数为：{params}")
                # 调用 tools/tool_use_hub.py 的 ToolUseHub.tool_use()，参数补齐后真实调用目标接口
                single_tool_response = self.toolUseHub.tool_use(tool, params)
                # 打调试日志：记录接口返回的响应
                logger.debug(f"[{query}]工具{tool.operationId}调用完成,响应为：{single_tool_response}")
                # HTTP 调用失败：返回异常节点
                if single_tool_response.status_code != RESPONSE_STATUS_CODE_SUCCESS:
                    # 组装调用失败结果
                    return {
                        "code": TASK_ERROR_CODE,
                        "result": "",
                        "tool": "异常调用节点-调用外部系统失败",
                        "missing_param": [],
                        "param": {},
                        "query": query,
                        "task_description": "调用外部系统失败"
                    }
                else:
                    # 调用成功：返回正常结果，missing_param 里带上补参链供前端画图
                    return {
                        "code": TASK_SUCCESS_CODE,
                        "tool": tool.name_for_human,
                        "result": single_tool_response.text,
                        "missing_param": missing_params_supplemented,
                        "param": params,
                        "query": query,
                        "task_description": query
                    }

    # 方法：多 API 规划——拆任务后循环执行单 API 规划直到完成，返回 (API 调用链, 总结文案)
    def apis_planning(self, query, task_id):

        # 内部辅助函数：执行一次单 API 规划并把结果追加进调用链（函数里定义函数 ≈ 局部方法/lambda）
        def process_single_api_invoke(curr_task_desc):
            # 调用本类 single_api_planning()，完成一次"选工具→提参数→调接口"
            api_invoke_result = self.single_api_planning(curr_task_desc, raw_query,api_chain)
            # 打调试日志：记录本次工具调用结果
            logger.debug(f"[{query}]工具调用结果：{api_invoke_result}")
            # 把本次结果追加到调用链列表（api_chain 是外层函数变量，闭包引用）
            api_chain.append(api_invoke_result)
            # 本次调用失败：写库并标记任务结束
            if api_invoke_result["code"] == TASK_ERROR_CODE:
                # 打调试日志：调用失败中止任务
                logger.debug(f"[{query}]工具调用失败，中止任务...")
                # 调用本类 convert_inter_result()，把失败的调用链写入 MongoDB 并标记结束
                self.convert_inter_result(task_id, api_chain, api_invoke_result["task_description"], True)
            # 解决调用函数时返回结果过多的问题：算出允许保留的最大结果长度
            api_result_length_limit = int(api_result_max_length * api_result_max_threshold)
            # 取出本次接口返回结果的字符长度
            api_invoke_result_length = len(api_invoke_result["result"])
            # 底层实现，不用看：结果超长就截断，防止撑爆 LLM 上下文
            if api_invoke_result_length >= api_result_length_limit:
                # 打警告日志：结果超长进行截取
                logger.warning(f"[{query}]API调用结果长度超出限制，截取长度{api_result_length_limit}...")
                # 切片截取前 N 个字符（≈ String.substring）
                api_result_fact = api_invoke_result["result"][:api_result_length_limit]
                # 把"已截取"提示和截留内容写回结果字段
                api_invoke_result["result"] = f"API调用结果长度为{api_invoke_result_length}超出限制，进行了截取，保留的内容为：{api_result_fact}"
            # 打调试日志：记录处理后的最终调用结果
            logger.debug(f"[{query}]工具实际调用结果：{api_invoke_result}")
            # 返回本次 API 调用结果
            return api_invoke_result

        # 内部辅助函数：在单 API 调用基础上追加死循环检测，返回 (是否可继续, 本次调用结果)
        def process_mul_task_api_invoke(curr_task_desc):
            # 调用本类 process_single_api_invoke()，先执行一次单 API 规划与调用
            api_invoke_result = process_single_api_invoke(curr_task_desc)
            # 打调试日志：记录本次调用结果
            logger.debug(f"[{query}]工具调用结果：{api_invoke_result}")
            # 调用本类 loop_validate()，检测调用链是否出现循环调用
            if not self.loop_validate(api_chain):
                # 打调试日志：发现循环调用中止任务
                logger.debug(f"[{query}]存在工具循环调用，中止任务...")
                # 调用本类 convert_inter_result()，把"循环调用错误"写库并结束任务
                self.convert_inter_result(task_id, api_chain, "循环调用错误", True)
                # 返回 False 表示不能再继续（元组多返回值）
                return False,api_invoke_result
            # 没检测到循环，返回 True 允许继续往下走
            return True, api_invoke_result

        # 保存用户原始提问，后续子任务描述会带上它做上下文
        raw_query = query
        # 初始化 API 调用结果链列表（≈ List<Map<String,Object>>）
        api_chain = []
        # 调用 tasks/generate_task_hub.py 的 GenerateTaskHub.gen_root_task()，LLM 判断单/多任务并生成根任务描述
        is_single_task, root_task_description = self.generateTaskHub.gen_root_task(query)
        # 打日志：记录单/多任务判断结果和根任务描述
        logger.info(f"[{query}]任务是否单任务:{is_single_task},当前任务描述为：{root_task_description}")
        # 单任务：一次规划加调用即完成
        if is_single_task:
            # 调用本类 process_single_api_invoke()，执行这一次 API 规划与调用
            single_task_result = process_single_api_invoke(query)
            # 调用失败：直接返回调用链和失败原因
            if single_task_result["code"] == TASK_ERROR_CODE:
                # 返回调用链和失败说明
                return api_chain, single_task_result["task_description"]
            # 调用 tools 包的 ToolSummaryHub.tool_summary()，LLM 对调用链做总结
            summary = self.toolSummaryHub.tool_summary(query, api_chain)
            # 打调试日志：记录总结文案
            logger.debug(f"[{query}]任务完成，总结任务概要为：{summary}")
            # 调用本类 convert_inter_result()，把最终结果写入 MongoDB（isEnd=True 结束态）
            self.convert_inter_result(task_id, api_chain, summary, True)
            # 返回调用链和总结文案
            return api_chain, summary
        # 多任务分支：循环"执行子任务→生成下一个子任务"直到完成
        else:
            # 初始化任务是否完成的标记
            is_complete = False
            # 当前待执行的子任务描述先取根任务描述
            task_description = root_task_description
            # 任务未完成且任务描述不为空，则循环处理任务
            while not is_complete and task_description is not None:
                # 调用本类 process_mul_task_api_invoke()，执行当前子任务（带死循环检测）
                loop_validate_result,single_task_result = process_mul_task_api_invoke(task_description)
                # 子任务调用失败：返回调用链和失败原因
                if single_task_result["code"] == TASK_ERROR_CODE:
                    # 返回调用链和失败说明
                    return api_chain, single_task_result["task_description"]
                # 检测到循环调用：中止并返回
                if not loop_validate_result:
                    # 返回调用链和失败说明
                    return api_chain, single_task_result["task_description"]
                # 打调试日志：记录当前子任务已完成
                logger.debug(f"[{query}]任务的子任务完成：{task_description}")
                # 调用本类 convert_inter_result()，把中间进度写库（isEnd=False 不结束任务）
                self.convert_inter_result(task_id, api_chain, f"已处理完成子任务 {task_description}", False)
                # 调用 tasks/generate_task_hub.py 的 GenerateTaskHub.gen_from_context_task()，根据已有调用链生成下一个子任务
                is_complete, task_description = self.generateTaskHub.gen_from_context_task(query, api_chain)
                # 打调试日志：记录任务是否完成及后续任务描述
                logger.debug(f"[{query}]任务是否完成：{is_complete}，后续任务描述为：{task_description}")

            # 任务标注已完成但仍有剩余任务描述，补执行一次收尾
            if task_description is not None:
                # 调用本类 process_mul_task_api_invoke()，执行剩余任务
                loop_validate_result,single_task_result = process_mul_task_api_invoke()
                # 执行失败：返回调用链和失败原因
                if single_task_result["code"] == TASK_ERROR_CODE:
                    # 返回调用链和失败说明
                    return api_chain, single_task_result["task_description"]
                # 检测到循环调用：返回错误说明
                if not loop_validate_result:
                    # 返回"循环调用错误"
                    return api_chain, "循环调用错误"
        # 调用 tools 包的 ToolSummaryHub.tool_summary()，多任务全部执行完统一总结
        summary = self.toolSummaryHub.tool_summary(query, api_chain)
        # 打调试日志：记录总结文案
        logger.debug(f"[{query}]任务完成，总结任务概要为：{summary}")
        # 调用本类 convert_inter_result()，把最终结果写库（isEnd=True 结束态）
        self.convert_inter_result(task_id, api_chain, summary, True)
        # 返回调用链和总结文案
        return api_chain, summary


# if __name__ == "__main__"：直接运行本文件时才执行的本地测试入口（≈ Java 的 main 方法）
if __name__ == "__main__":
    # 第三方库 dotenv：从 .env 文件加载环境变量
    from dotenv import load_dotenv
    # 标准库 os：读环境变量（≈ System.getenv）
    import os
    # 标准库 uuid：生成唯一 ID（≈ UUID.randomUUID()）
    import uuid
    # 加载 .env 里的环境变量配置
    load_dotenv()
    # 读 milvus_uri 环境变量，第二个参数是默认值（≈ getOrDefault）
    milvus_uri = os.getenv("milvus_uri", "http://localhost:19530")
    # 读向量模型文件路径配置
    model_path = os.getenv("model_path", "model")
    # 读 Milvus 数据库名配置
    milvus_db_name = os.getenv("milvus_db_name", "tool_db")
    # 读大模型名称配置
    model = os.getenv("model", "qwen-max-0919")
    # 读采样温度并转 float（环境变量都是字符串，需手动转数字）
    temperature = float(os.getenv("temperature", "0.01"))
    # 读核采样概率并转 float
    top_p = float(os.getenv("top_p", "0.01"))
    # 读 MongoDB 主机地址
    mongo_host = os.getenv("mongo_host", "127.0.0.1")
    # 读 MongoDB 数据库名
    mongo_db = os.getenv("mongo_db", "tools")
    # 读 MongoDB 端口并转 int
    mongo_port = int(os.getenv("mongo_port", "27017"))
    # 读检索数量 topK 并转 int
    topK = int(os.getenv("topK", "5"))
    # 读大模型 API Key
    api_key = os.getenv("api_key", "")
    # 读大模型接口地址
    base_url = os.getenv("base_url", "")
    # 标准库 uuid 生成任务编号并转字符串
    task_id = str(uuid.uuid4())
    # 创建本类实例，组装好各配置准备做任务规划测试
    apiPlanningHub = ApiPlanningHub(milvus_uri, model_path, milvus_db_name, model, temperature, top_p,
                                    mongo_host, mongo_db, mongo_port, topK, base_url,api_key)
