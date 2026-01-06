# 开发文档

## 架构说明
本项目采用模块化设计，核心目录 fixedkeyfiles4 实现了工业级 RAG 全流程，包括：
- 数据预处理
- 特征提取
- 向量索引构建
- 增强检索与生成

## 开发流程
1. Fork 项目，创建开发分支
2. 主要开发在 fixedkeyfiles4 目录
3. 更新 requirements.txt 依赖
4. 单元与集成测试
5. 合并主分支

## 主要模块说明
- **fixedkeyfiles4**：核心RAG流程（retrieval/augmentation/generation）
- **data_ingest/**：数据采集与清洗
- **vector_db/**：向量存储与CRUD
- **models/**：AI模型调用与管理
- **api/**：接口层

## 代码贡献
请遵循PEP8规范，核心功能提交需附测试用例。
---