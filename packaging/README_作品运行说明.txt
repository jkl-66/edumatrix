EduMatrix 当前版本运行说明

一、启动
1. 将整个压缩包解压到可写目录，建议路径较短。安装 Windows 版 Python 3.11。
2. 把 .env.runtime.template 复制为 .env，在 EDUMATRIX_LLM_API_KEY 后填入可用密钥。
   默认模型为 DeepSeek；如使用其他兼容接口，同时修改 ENDPOINT 与 MODEL。
3. 双击 install_and_run.bat。首次联网安装依赖，随后自动打开 http://127.0.0.1:8000。
   本包包含预先计算的课程向量，启动时自动复用。课程更新后需要补算索引时，窗口会显示等待状态，请保留窗口。
   已有资源可直接学习；新生成、答疑和主观评分需要模型服务。
   CPU 本地检索模型已经包含，无需首次下载模型。端口被占用时，在 .env 修改 EDUMATRIX_PORT。

二、体验账号
以下均为合成演示账号，统一密码 EduMatrix2026!。
learner   软件背景：代表完整资源包与实训配套。
reviewer  经营背景：按需复习、测验及组卷报告。
explorer  新学习者：注册诊断后的全课路径与首个学习检查。
teacher   教师工作区。
admin     管理设置。

主体验课程：人工智能与深度学习：从机器学习基础到大模型智能体（1.4.4）。
以 learner 登录后，从资源中心打开已准备内容，或在学习路径选择当前任务生成资源。
生成在后台继续，刷新或重新登录可回到同一任务。资源准备好后打开学习，完成题目并阅读反馈，再回路径继续。
以 reviewer 可查看复习、组卷及已有报告；以 explorer 可查看诊断依据、全课安排及首个学习检查。

三、停止与恢复
双击 stop_services.bat。正在生成的内容保存完成后服务退出；排队任务留待下次启动继续。
再次运行 install_and_run.bat，沿原账号继续。请保留本目录的 edumatrix.db，学习记录保存在该文件中。
修改 .env 后正常停止并重新启动。401/402 等账号问题需要先恢复密钥或额度，系统保留进度。
启动错误见 .runtime/server-error.log；安装失败后修复网络并重新运行启动脚本即可。

四、运行条件与数据
首次安装需要联网下载 Python 依赖；常规使用需要可访问模型接口。代码练习在本机 trusted_local 模式运行，不要求 Docker。
默认专用Python环境位于 %LOCALAPPDATA%\EduMatrix\current\.venv，可用 EDUMATRIX_VENV_PATH 指定其他目录。
本包不含开发密钥。预置账号、画像和练习输入均为合成资料，当前资源与反馈保留实际生成/评分结果。
第三方课程、模型与库的来源见 THIRD_PARTY_RUNTIME.md。实际独立解压及重启结果见压缩包旁的 DELIVERY_RESULT.json。
