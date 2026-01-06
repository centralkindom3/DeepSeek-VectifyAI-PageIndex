```mermaid
graph TB
    A[原始数据] --> B{fixedkeyfiles4}
    B --> C[预处理]
    C --> D[特征提取]
    D --> E[向量索引]
    E --> F[检索]
    F --> G[RAG生成]
    G --> H[输出]
```
---