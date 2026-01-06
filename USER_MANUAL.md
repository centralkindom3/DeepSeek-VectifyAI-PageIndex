# 用户手册

## 1. 安装配置
1. 安装 Python>=3.10
2. `pip install -r requirements.txt`
3. 启动服务/运行脚本：`python main.py` 或 `uvicorn api:app --reload`

## 2. 功能介绍
### fixedkeyfiles4 - 工业级RAG流程
- 自动将各类页面/文档进行切割、特征提取及向量化处理
- 构建高效索引
- 支持语义检索，基于AI智能生成相关内容和精准回答

## 3. 基本用法
#### 页面/文档索引与检索
1. 上传文档或配置数据源
2. 系统自动处理至 fixedkeyfiles4
3. 检索问题，系统自动关联上下文，调用AI完成生成式回答

#### 进阶用法
- 批量文档自动摘要
- 跨数据源混合检索
- 结合生成API实现自动答复

## 4. 常见问题
- 无法检索结果？确认数据已索引，更新 fixedkeyfiles4 目录内容
- 性能优化措施：合理分片、向量库配置

## 5. 技术支持
前往 [GitHub 项目主页](https://github.com/centralkindom3/DeepSeek-VectifyAI-PageIndex) 反馈问题或获取更多帮助。
---