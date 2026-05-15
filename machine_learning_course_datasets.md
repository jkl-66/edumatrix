# 机器学习导论课程数据集清单

本项目固定课程场景为“机器学习导论”。数据集选择遵循三个原则：

1. 适合高校课程教学，从入门分类、回归到综合项目逐步递进。
2. 来源公开、稳定、可复现，便于评委现场复查。
3. 能支撑个性化资源生成、实操代码案例、练习题、错因诊断和教师端干预建议。

| 数据集 | URL | 教学用途 | 推荐章节 |
|---|---|---|---|
| Iris | https://archive.ics.uci.edu/dataset/53/iris | 分类入门、特征可视化、KNN/逻辑回归 | 监督学习入门 |
| Wine | https://archive.ics.uci.edu/dataset/109/wine | 多分类、标准化、正则化、交叉验证 | 模型选择与正则化 |
| Breast Cancer Wisconsin Diagnostic | https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic | 二分类、混淆矩阵、precision/recall/F1 | 分类评估 |
| Diabetes | https://scikit-learn.org/stable/datasets/toy_dataset.html#diabetes-dataset | 线性回归、回归误差、特征解释 | 回归模型 |
| California Housing | https://scikit-learn.org/stable/modules/generated/sklearn.datasets.fetch_california_housing.html | 综合回归项目、训练测试划分、泛化误差 | 机器学习项目实践 |
| MNIST 784 | https://www.openml.org/d/554 | 图像分类、多模态扩展、神经网络入门 | 拓展项目 |
| Adult | https://archive.ics.uci.edu/dataset/2/adult | 分类、公平性、特征偏差与伦理讨论 | AI 伦理与模型评估 |
| Auto MPG | https://archive.ics.uci.edu/dataset/9/auto+mpg | 回归、缺失值处理、特征工程 | 数据预处理 |

## 比赛演示建议

第一轮演示不追求数据集数量，而追求教学闭环完整：

1. **Iris**：让学生快速理解监督学习和分类边界。
2. **Breast Cancer**：展示混淆矩阵、precision/recall/F1 和误概念诊断。
3. **Wine**：展示标准化、正则化和交叉验证。
4. **Diabetes 或 California Housing**：展示回归项目与泛化误差。

教师端可围绕 Breast Cancer 的分类评估单元展示班级误概念排行：

- accuracy 与 recall 混淆。
- 训练集分数高就认为模型好。
- 忽视类别不均衡。
- 不知道何时使用 F1。

这些误概念可以直接触发 EduMatrix 的反例辨析、检索练习、元认知校准和间隔复习策略。
