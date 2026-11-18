# AI技能识别词典（ai_skill_dict_v1.0_2026-11-18）

本文件由 `code/python/34_write_wordlist_v1.py` 自动生成，不要手改；程序读取的是 `config/ai_skill_dictionary_v1.0.json`（终版，已冻结）。

## 层级含义

- **严格**：含义基本唯一的AI技术词。出现在非公司介绍句中即计入 ai_skill。
- **宽泛**：AI相关但容易误判的词。只在同一句含有岗位要求/职责线索时计入 ai_skill_broad，不进入 ai_skill。
- **待审**：AI相邻但是否算AI技能有争议的词。只记录为 ai_review_flag，用于人工标注分层抽样，不进入任何AI变量。
- **条件**：v0.2新增。出现在非公司介绍句中，且同一广告还有另一个不同的严格词或条件词时才计入 ai_skill；否则只记入 ai_conditional_terms 和 ai_skill_broad。

“写法”是正则表达式：`|` 表示“或”，`(?:…)` 是分组，`(?<!…)`、`(?!…)` 表示前后不能紧挨某些字。

## 严格词（138个）

|编号|写法|类别|种子组|相关度|来源|v0.2改动|
|---|---|---|---|---:|---|---|
|aahr_keras|`Keras`|传统AI|工具框架|84.3%|Acemoglu等清单||
|aahr_mahout|`Mahout`|传统AI|工具框架|50.5%|Acemoglu等清单||
|aahr_opencv|`OpenCV`|传统AI|工具框架|40.7%|Acemoglu等清单||
|aahr_xgboost|`XGBoost`|传统AI|工具框架|81.5%|Acemoglu等清单||
|w_cntk|`cntk`|传统AI|工具框架|73.8%|Word2Vec新增||
|w_darknet|`darknet`|传统AI|工具框架|60.7%|Word2Vec新增||
|w_dlib|`dlib`|传统AI|工具框架|63.6%|Word2Vec新增||
|w_gensim|`gensim`|传统AI|工具框架|100.0%|Word2Vec新增||
|w_madlib|`madlib`|传统AI|工具框架|2.9%|Word2Vec新增||
|w_mask_r|`mask[ _-]?r`|传统AI|工具框架|82.2%|Word2Vec新增||
|w_scikit|`scikit`|传统AI|工具框架|90.5%|Word2Vec新增||
|w_tensflow|`tensflow`|传统AI|工具框架|80.0%|Word2Vec新增||
|w_theano|`theano`|传统AI|工具框架|88.6%|Word2Vec新增||
|w_weka|`weka`|传统AI|工具框架|76.3%|Word2Vec新增||
|x_ml_frameworks|`TensorFlow\|PyTorch\|Caffe\|scikit-?learn\|sklearn\|LightGBM\|PaddlePaddle\|飞桨\|MindSpore\|MXNet\|ONNX\|TensorRT\|YOLO\|BERT`|传统AI|工具框架|75.0%|项目补充||
|w_widedeep|`widedeep`|传统AI|工具框架;推荐与搜索;深度学习;语言与语音|69.8%|Word2Vec新增||
|w_deepfm|`deepfm`|传统AI|工具框架;机器学习方法|87.2%|Word2Vec新增||
|w_knn|`knn`|传统AI|工具框架;机器学习方法|87.0%|Word2Vec新增||
|w_adaboost|`adaboost`|传统AI|工具框架;机器学习方法;深度学习|91.4%|Word2Vec新增||
|w_xgb|`xgb`|传统AI|工具框架;机器学习方法;深度学习|88.1%|Word2Vec新增||
|w_集成学习|`集成学习`|传统AI|工具框架;机器学习方法;深度学习|95.7%|Word2Vec新增||
|w_doc2vec|`doc2vec`|传统AI|工具框架;机器学习方法;深度学习;生成式AI;语言与语音|93.5%|Word2Vec新增||
|w_dbscan|`dbscan`|传统AI|工具框架;机器学习方法;深度学习;语言与语音|51.6%|Word2Vec新增||
|w_ftrl|`ftrl`|传统AI|工具框架;机器学习方法;深度学习;语言与语音|100.0%|Word2Vec新增||
|w_randomforest|`randomforest`|传统AI|工具框架;机器学习方法;语言与语音|79.3%|Word2Vec新增||
|w_w2v|`w2v`|传统AI|工具框架;机器学习方法;语言与语音|100.0%|Word2Vec新增||
|w_faster_r|`faster[ _-]?r`|传统AI|工具框架;深度学习|78.8%|Word2Vec新增||
|w_googlenet|`googlenet`|传统AI|工具框架;深度学习|70.6%|Word2Vec新增||
|w_mobilenet|`mobilenet`|传统AI|工具框架;深度学习|63.6%|Word2Vec新增||
|w_resnet|`resnet`|传统AI|工具框架;深度学习|70.6%|Word2Vec新增||
|w_seq2seq|`seq2seq`|传统AI|工具框架;深度学习|97.2%|Word2Vec新增||
|w_vgg|`vgg`|传统AI|工具框架;深度学习|60.4%|Word2Vec新增||
|w_gru|`gru`|传统AI|工具框架;深度学习;生成式AI|87.5%|Word2Vec新增||
|w_vgg16|`vgg16`|传统AI|工具框架;深度学习;生成式AI|90.9%|Word2Vec新增||
|w_convnet|`convnet`|传统AI|工具框架;生成式AI|87.8%|Word2Vec新增||
|w_deeplab|`deeplab`|传统AI|工具框架;生成式AI|53.3%|Word2Vec新增||
|w_deeplearning4j|`deeplearning4j`|传统AI|工具框架;生成式AI|91.4%|Word2Vec新增||
|w_deepspeed|`deepspeed`|传统AI|工具框架;生成式AI|67.3%|Word2Vec新增||
|w_megatron|`megatron`|传统AI|工具框架;生成式AI|69.1%|Word2Vec新增||
|w_mnn|`mnn`|传统AI|工具框架;生成式AI|46.7%|Word2Vec新增||
|w_openvino|`openvino`|传统AI|工具框架;生成式AI|56.2%|Word2Vec新增||
|w_rknn|`rknn`|传统AI|工具框架;生成式AI|46.9%|Word2Vec新增||
|w_sglang|`sglang`|传统AI|工具框架;生成式AI|28.6%|Word2Vec新增||
|w_tenorflow|`tenorflow`|传统AI|工具框架;生成式AI|93.8%|Word2Vec新增||
|w_tensor_flow|`tensor[ _-]?flow`|传统AI|工具框架;生成式AI|71.0%|Word2Vec新增||
|w_tflite|`tflite`|传统AI|工具框架;生成式AI|34.1%|Word2Vec新增||
|w_triton|`triton`|传统AI|工具框架;生成式AI|42.4%|Word2Vec新增||
|w_unet|`unet`|传统AI|工具框架;生成式AI|56.0%|Word2Vec新增||
|w_xlnet|`xlnet`|传统AI|工具框架;生成式AI|100.0%|Word2Vec新增||
|w_模型剪枝|`模型剪枝`|传统AI|工具框架;生成式AI|77.1%|Word2Vec新增||
|w_知识蒸馏|`知识蒸馏`|传统AI|工具框架;生成式AI|80.0%|Word2Vec新增||
|aahr_recommender_systems|`推荐系统\|推荐算法\|个性化推荐\|Recommender Systems?`|传统AI|推荐与搜索|63.4%|Acemoglu等清单||
|x_ctr|`CTR预估\|搜索排序算法`|传统AI|推荐与搜索|61.1%|项目补充||
|x_knowledge_graph|`知识图谱`|传统AI|推荐与搜索|73.9%|项目补充||
|w_learningtorank|`learningtorank`|传统AI|推荐与搜索;机器学习方法;语言与语音|94.7%|Word2Vec新增||
|w_deeplearning|`deeplearning`|传统AI|推荐与搜索;深度学习|84.0%|Word2Vec新增||
|w_意图识别|`意图识别`|传统AI|推荐与搜索;计算机视觉;语言与语音|86.2%|Word2Vec新增||
|w_关系抽取|`关系抽取`|传统AI|推荐与搜索;语言与语音|92.7%|Word2Vec新增||
|w_命名实体识别|`命名实体识别`|传统AI|推荐与搜索;语言与语音|97.9%|Word2Vec新增||
|w_实体识别|`实体识别`|传统AI|推荐与搜索;语言与语音|94.8%|Word2Vec新增||
|w_文本分类|`文本分类`|传统AI|推荐与搜索;语言与语音|93.5%|Word2Vec新增||
|w_语义理解|`语义理解`|传统AI|推荐与搜索;语言与语音|84.8%|Word2Vec新增||
|aahr_gradient_boosting|`梯度提升\|GBDT\|Gradient Boosting`|传统AI|机器学习方法|82.5%|Acemoglu等清单||
|aahr_machine_learning|`机器学习\|Machine Learning`|传统AI|机器学习方法|32.0%|Acemoglu等清单||
|aahr_random_forests|`随机森林\|Random Forests?`|传统AI|机器学习方法|83.0%|Acemoglu等清单||
|aahr_supervised_learning|`监督学习\|Supervised Learning`|传统AI|机器学习方法|82.2%|Acemoglu等清单||
|aahr_svm|`支持向量机\|SVM`|传统AI|机器学习方法|88.2%|Acemoglu等清单||
|aahr_unsupervised_learning|`无监督学习\|Unsupervised Learning`|传统AI|机器学习方法|93.1%|Acemoglu等清单||
|w_sgd|`sgd`|传统AI|机器学习方法|96.7%|Word2Vec新增||
|x_ml_algorithms|`朴素贝叶斯`|传统AI|机器学习方法|81.2%|项目补充||
|w_a3c|`a3c`|传统AI|机器学习方法;深度学习|33.3%|Word2Vec新增||
|w_arima|`arima`|传统AI|机器学习方法;深度学习|62.2%|Word2Vec新增||
|w_bagging|`bagging`|传统AI|机器学习方法;深度学习|78.8%|Word2Vec新增||
|w_ddpg|`ddpg`|传统AI|机器学习方法;深度学习|22.6%|Word2Vec新增||
|w_dqn|`dqn`|传统AI|机器学习方法;深度学习|53.1%|Word2Vec新增||
|w_gnn|`gnn`|传统AI|机器学习方法;深度学习|84.6%|Word2Vec新增||
|w_神经元网络|`神经元网络`|传统AI|机器学习方法;深度学习|62.0%|Word2Vec新增||
|w_autoencoder|`autoencoder`|传统AI|机器学习方法;语言与语音|97.2%|Word2Vec新增||
|w_maxent|`maxent`|传统AI|机器学习方法;语言与语音|100.0%|Word2Vec新增||
|w_plsa|`plsa`|传统AI|机器学习方法;语言与语音|97.1%|Word2Vec新增||
|aahr_deep_learning|`深度学习\|Deep Learning`|传统AI|深度学习|74.8%|Acemoglu等清单||
|aahr_neural_networks|`神经网络\|Neural Networks?`|传统AI|深度学习|71.1%|Acemoglu等清单||
|w_object_detection|`object[ _-]?detection`|传统AI|深度学习|89.7%|Word2Vec新增||
|w_pomdp|`pomdp`|传统AI|深度学习|29.4%|Word2Vec新增||
|w_reinforcementlearning|`reinforcementlearning`|传统AI|深度学习|92.3%|Word2Vec新增||
|x_gan|`GAN`|传统AI|深度学习|81.5%|项目补充||
|x_nn_architectures|`卷积神经\|循环神经\|RNN\|LSTM\|生成对抗网络`|传统AI|深度学习|82.2%|项目补充||
|x_reinforcement_learning|`强化学习\|Reinforcement Learning`|传统AI|深度学习|77.8%|项目补充||
|w_vla|`vla`|传统AI|深度学习;生成式AI|57.1%|Word2Vec新增||
|w_注意力机制|`注意力机制`|传统AI|深度学习;生成式AI|79.5%|Word2Vec新增||
|b_llm_bare|`(?<![放扩最巨庞])大模型`|生成式AI|生成式AI|64.4%|项目补充（生成式）|宽泛词→严格词（唯一的升级例外）：ChatGPT后单独出现基本指大语言模型；三维模型用法由排除规则去掉；不按年份划分词义|
|g_agent|`AI ?Agent\|智能体(?!验)\|LLM ?Agent`|生成式AI|生成式AI|60.1%|项目补充（生成式）||
|g_aigc|`AIGC`|生成式AI|生成式AI|30.7%|项目补充（生成式）||
|g_chatgpt|`ChatGPT`|生成式AI|生成式AI|35.1%|项目补充（生成式）||
|g_cn_llm_products|`文心一言\|通义千问\|DeepSeek\|ChatGLM\|讯飞星火\|豆包大模型\|Qwen\|LLaMA\|Llama ?[23]`|生成式AI|生成式AI|69.0%|项目补充（生成式）||
|g_copilot|`Copilot`|生成式AI|生成式AI|44.3%|项目补充（生成式）||
|g_finetune|`(?:大模型\|模型\|LLM)\s*(?:微调\|精调)\|fine-?tun(?:e\|ing)\|SFT\|RLHF\|指令微调`|生成式AI|生成式AI|85.5%|项目补充（生成式）||
|g_genai|`生成式(?:人工智能\|AI\|模型)\|Generative AI\|GenAI`|生成式AI|生成式AI|49.2%|项目补充（生成式）||
|g_gpt|`GPT(?:-?[0-9](?:\.[0-9])?o?)?`|生成式AI|生成式AI|70.2%|项目补充（生成式）||
|g_llm_en|`LLMs?`|生成式AI|生成式AI|63.2%|项目补充（生成式）||
|g_llm_frameworks|`LangChain\|LlamaIndex\|Hugging ?Face\|vLLM\|Dify`|生成式AI|生成式AI|72.8%|项目补充（生成式）||
|g_llm_zh|`大语言模型\|(?:AI\|人工智能\|预训练\|多模态\|通用\|行业\|垂直\|开源)大模型\|大模型(?:技术\|算法\|应用\|训练\|微调\|推理\|开发\|产品\|能力)`|生成式AI|生成式AI|20.6%|项目补充（生成式）||
|g_prompt_eng|`提示词\|Prompt ?(?:工程\|设计\|Engineering\|Engineer)`|生成式AI|生成式AI|76.1%|项目补充（生成式）||
|g_rag|`RAG\|检索增强生成`|生成式AI|生成式AI|82.8%|项目补充（生成式）||
|w_autogen|`autogen`|生成式AI|生成式AI|83.9%|Word2Vec新增||
|w_autogpt|`autogpt`|生成式AI|生成式AI|82.5%|Word2Vec新增||
|w_coze|`coze`|生成式AI|生成式AI|68.1%|Word2Vec新增||
|w_langgraph|`langgraph`|生成式AI|生成式AI|84.4%|Word2Vec新增||
|w_nerf|`nerf`|生成式AI|生成式AI|4.5%|Word2Vec新增||
|w_sora|`sora`|生成式AI|生成式AI|63.9%|Word2Vec新增||
|w_spacy|`spacy`|生成式AI|生成式AI|58.3%|Word2Vec新增||
|w_模型推理|`模型推理`|生成式AI|生成式AI|58.5%|Word2Vec新增||
|w_豆包|`豆包`|生成式AI|生成式AI|33.0%|Word2Vec新增||
|w_通义|`通义`|生成式AI|生成式AI|18.8%|Word2Vec新增||
|w_图像生成|`图像生成`|传统AI|生成式AI;计算机视觉|67.0%|Word2Vec新增||
|w_al_agent|`al[ _-]?agent`|传统AI|生成式AI;语言与语音|54.8%|Word2Vec新增||
|w_fastgpt|`fastgpt`|传统AI|生成式AI;语言与语音|30.6%|Word2Vec新增||
|aahr_computer_vision|`计算机视觉\|Computer Vision`|传统AI|计算机视觉|52.6%|Acemoglu等清单||
|aahr_image_recognition|`图像识别\|图片识别\|Image Recognition`|传统AI|计算机视觉|60.5%|Acemoglu等清单||
|aahr_object_recognition|`物体识别\|目标识别\|Object Recognition`|传统AI|计算机视觉|58.2%|Acemoglu等清单||
|aahr_pattern_recognition|`(?<!业务\|商业\|经营)模式识别(?!与智能系统)`|传统AI|计算机视觉|69.0%|Acemoglu等清单||
|w_reid|`reid`|传统AI|计算机视觉|53.1%|Word2Vec新增||
|w_字符识别|`字符识别`|传统AI|计算机视觉|46.9%|Word2Vec新增||
|x_cv_tasks|`人脸识别\|目标检测\|图像分割\|语义分割\|OCR识别`|传统AI|计算机视觉|54.5%|项目补充||
|w_实例分割|`实例分割`|传统AI|计算机视觉;语言与语音|68.0%|Word2Vec新增||
|aahr_ai_chatbot|`聊天机器人\|对话机器人\|问答机器人\|Chat ?bot`|传统AI|语言与语音|74.0%|Acemoglu等清单||
|aahr_machine_translation|`机器翻译\|Machine Translation`|传统AI|语言与语音|81.2%|Acemoglu等清单||
|aahr_nlp|`自然语言处理\|自然语言理解\|NLP\|NLU`|传统AI|语言与语音|66.8%|Acemoglu等清单||
|aahr_sentiment_analysis|`情感分析\|观点挖掘\|意见挖掘\|Sentiment Analysis\|Opinion Mining`|传统AI|语言与语音|93.9%|Acemoglu等清单||
|aahr_speech_recognition|`语音识别\|ASR`|传统AI|语言与语音|55.8%|Acemoglu等清单||
|aahr_text_mining|`文本挖掘\|Text Mining`|传统AI|语言与语音|87.0%|Acemoglu等清单||
|aahr_virtual_agents|`虚拟助手\|智能助理\|虚拟代理\|Virtual Agents?`|传统AI|语言与语音|52.6%|Acemoglu等清单||
|aahr_word2vec|`Word2vec\|词向量`|传统AI|语言与语音|96.9%|Acemoglu等清单||
|w_nlg|`nlg`|传统AI|语言与语音|100.0%|Word2Vec新增||
|w_wfst|`wfst`|传统AI|语言与语音|36.4%|Word2Vec新增||
|w_句法分析|`句法分析`|传统AI|语言与语音|98.4%|Word2Vec新增||
|w_消歧|`消歧`|传统AI|语言与语音|94.2%|Word2Vec新增||
|x_speech_synthesis|`语音合成\|声纹识别`|传统AI|语言与语音|50.4%|项目补充||

## 条件词（76个）

|编号|写法|类别|种子组|相关度|来源|v0.2改动|
|---|---|---|---|---:|---|---|
|aahr_libsvm|`LibSVM`|传统AI|工具框架|100.0%|Acemoglu等清单|严格词→条件词：出现不足30条，默认条件词|
|w_cognex_visionpro|`cognex[ _-]?visionpro`|传统AI|工具框架|0.0%|Word2Vec新增||
|w_h2o|`h2o`|传统AI|工具框架|67.4%|Word2Vec新增||
|w_ni_vision|`ni[ _-]?vision`|传统AI|工具框架|8.7%|Word2Vec新增||
|w_nivision|`nivision`|传统AI|工具框架|17.3%|Word2Vec新增||
|w_open3d|`open3d`|传统AI|工具框架|36.5%|Word2Vec新增||
|w_openc|`openc`|传统AI|工具框架|47.6%|Word2Vec新增||
|w_openni|`openni`|传统AI|工具框架|91.2%|Word2Vec新增||
|w_paddle|`paddle`|传统AI|工具框架|62.4%|Word2Vec新增||
|w_torch|`torch`|传统AI|工具框架|86.1%|Word2Vec新增||
|w_tvm|`tvm`|传统AI|工具框架|24.0%|Word2Vec新增||
|w_深林|`深林`|传统AI|工具框架;机器学习方法|84.9%|Word2Vec新增||
|w_gbm|`gbm`|传统AI|工具框架;机器学习方法;深度学习|61.8%|Word2Vec新增||
|w_fcn|`fcn`|传统AI|工具框架;深度学习|86.6%|Word2Vec新增||
|w_vit|`vit`|传统AI|工具框架;生成式AI|56.2%|Word2Vec新增||
|w_visonpro|`visonpro`|传统AI|工具框架;计算机视觉|16.1%|Word2Vec新增||
|w_模拟退火|`模拟退火`|传统AI|推荐与搜索|54.5%|Word2Vec新增||
|w_精排|`精排`|传统AI|推荐与搜索|59.4%|Word2Vec新增||
|w_对话系统|`对话系统`|传统AI|推荐与搜索;计算机视觉;语言与语音|86.7%|Word2Vec新增||
|w_问答系统|`问答系统`|传统AI|推荐与搜索;计算机视觉;语言与语音|91.3%|Word2Vec新增||
|w_ranking|`ranking`|传统AI|推荐与搜索;语言与语音|58.3%|Word2Vec新增||
|w_信息抽取|`信息抽取`|传统AI|推荐与搜索;语言与语音|68.0%|Word2Vec新增||
|aahr_kernel_methods|`核函数\|Kernel Methods?`|传统AI|机器学习方法|0.0%|Acemoglu等清单|严格词→条件词：出现不足30条，默认条件词|
|aahr_lda|`潜在狄利克雷分配\|LDA主题模型\|Latent Dirichlet Allocation`|传统AI|机器学习方法|80.0%|Acemoglu等清单|严格词→条件词：出现不足30条，默认条件词|
|aahr_lsa|`潜在语义分析\|Latent Semantic Analysis`|传统AI|机器学习方法||Acemoglu等清单|严格词→条件词：出现不足30条，默认条件词|
|w_lr|`lr`|传统AI|机器学习方法|42.4%|Word2Vec新增||
|w_如聚类|`如聚类`|传统AI|机器学习方法|65.4%|Word2Vec新增||
|w_贝叶斯|`贝叶斯`|传统AI|机器学习方法|78.2%|Word2Vec新增||
|w_马尔科夫|`马尔科夫`|传统AI|机器学习方法|57.1%|Word2Vec新增||
|w_boosting|`boosting`|传统AI|机器学习方法;深度学习|95.4%|Word2Vec新增||
|w_gmm|`gmm`|传统AI|机器学习方法;深度学习;语言与语音|68.9%|Word2Vec新增||
|w_lda|`lda`|传统AI|机器学习方法;深度学习;语言与语音|88.8%|Word2Vec新增||
|w_ltr|`ltr`|传统AI|机器学习方法;语言与语音|72.7%|Word2Vec新增||
|w_dnn|`dnn`|传统AI|深度学习|76.8%|Word2Vec新增||
|w_hog|`hog`|传统AI|深度学习|89.6%|Word2Vec新增||
|w_inception|`inception`|传统AI|深度学习|7.2%|Word2Vec新增||
|w_inference|`inference`|传统AI|深度学习|76.7%|Word2Vec新增||
|w_rbm|`rbm`|传统AI|深度学习|80.3%|Word2Vec新增||
|w_rl|`rl`|传统AI|深度学习|75.5%|Word2Vec新增||
|w_diffusion|`diffusion`|传统AI|深度学习;生成式AI|47.3%|Word2Vec新增||
|w_vae|`vae`|传统AI|深度学习;生成式AI|70.6%|Word2Vec新增||
|w_vlm|`vlm`|传统AI|深度学习;生成式AI|61.5%|Word2Vec新增||
|g_image_gen_tools|`Midjourney\|Stable ?Diffusion\|ComfyUI\|文生图\|图生图\|文生视频\|AI绘画\|AI绘图\|AI作画\|AI生图\|扩散模型`|生成式AI|生成式AI|21.1%|项目补充（生成式）|严格词→条件词：相关度21.1%<30%|
|w_agi|`agi`|生成式AI|生成式AI|31.6%|Word2Vec新增||
|w_ann|`ann`|生成式AI|生成式AI|15.8%|Word2Vec新增||
|w_bloom|`bloom`|生成式AI|生成式AI|90.9%|Word2Vec新增||
|w_milvus|`milvus`|生成式AI|生成式AI|64.4%|Word2Vec新增||
|w_palm|`palm`|生成式AI|生成式AI|88.9%|Word2Vec新增||
|w_runway|`runway`|生成式AI|生成式AI|8.6%|Word2Vec新增||
|w_t5|`t5`|生成式AI|生成式AI|70.7%|Word2Vec新增||
|w_可灵|`可灵(?!活)`|生成式AI|生成式AI|2.2%|Word2Vec新增||
|w_微调|`微调`|生成式AI|生成式AI|69.0%|Word2Vec新增||
|w_精调|`(?<!香)精调`|生成式AI|生成式AI|60.0%|Word2Vec新增||
|w_预训练|`预训练`|生成式AI|生成式AI|81.2%|Word2Vec新增||
|w_gcn|`gcn`|传统AI|生成式AI;语言与语音|83.0%|Word2Vec新增||
|w_智谱|`智谱`|传统AI|生成式AI;语言与语音|18.8%|Word2Vec新增||
|aahr_image_processing|`数字图像处理\|图像处理算法\|Image Processing`|传统AI|计算机视觉|36.5%|Acemoglu等清单||
|aahr_machine_vision|`机器视觉\|Machine Vision`|传统AI|计算机视觉|21.3%|Acemoglu等清单|严格词→条件词：相关度21.3%<30%|
|w_sherlock|`sherlock`|传统AI|计算机视觉|6.8%|Word2Vec新增||
|w_三维重建|`三维重建`|传统AI|计算机视觉|57.2%|Word2Vec新增||
|w_光流|`(?<![抛布验荧心])光流(?![程式美])`|传统AI|计算机视觉|43.9%|Word2Vec新增||
|w_去模糊|`去模糊`|传统AI|计算机视觉|63.7%|Word2Vec新增||
|w_图像匹配|`图像匹配`|传统AI|计算机视觉|46.1%|Word2Vec新增||
|w_图像去噪|`图像去噪`|传统AI|计算机视觉|48.5%|Word2Vec新增||
|w_图像增强|`图像增强`|传统AI|计算机视觉|48.5%|Word2Vec新增||
|w_姿态估计|`姿态估计`|传统AI|计算机视觉|66.0%|Word2Vec新增||
|w_视频分析|`视频分析`|传统AI|计算机视觉|57.6%|Word2Vec新增||
|w_视频分类|`视频分类`|传统AI|计算机视觉|67.4%|Word2Vec新增||
|w_声纹|`声纹`|传统AI|计算机视觉;语言与语音|44.5%|Word2Vec新增||
|w_文本检索|`文本检索`|传统AI|计算机视觉;语言与语音|99.3%|Word2Vec新增||
|aahr_sentiment_classification|`情感分类\|Sentiment Classification`|传统AI|语言与语音|100.0%|Acemoglu等清单|严格词→条件词：出现不足30条，默认条件词|
|w_hmm|`hmm`|传统AI|语言与语音|77.6%|Word2Vec新增||
|w_lsa|`lsa`|传统AI|语言与语音|85.1%|Word2Vec新增||
|w_词性|`词性`|传统AI|语言与语音|96.3%|Word2Vec新增||
|w_超分|`超分(?![支公析院])`|传统AI|语言与语音|53.9%|Word2Vec新增||
|w_达摩院|`达摩院`|传统AI|语言与语音|22.6%|Word2Vec新增||

## 宽泛词（23个）

|编号|写法|类别|种子组|相关度|来源|v0.2改动|
|---|---|---|---|---:|---|---|
|aahr_predictive_models|`预测模型\|Predictive Models?`|传统AI||29.9%|Acemoglu等清单|相关度29.9%达到conditional门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_ai_en|`AI`|未区分||27.1%|Acemoglu等宽口径|相关度27.1%达到conditional门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_ai_major|`模式识别与智能系统\|智能科学与技术`|未区分||20.1%|项目补充|相关度20.1%达到conditional门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_ai_tools|`AI工具\|AI软件\|AI技术\|AI应用\|AI产品\|AI编程\|AI辅助\|AI写作\|AI生成\|AI视频\|AI剪辑`|未区分||33.4%|项目补充（生成式）|相关度33.4%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_ai_zh|`人工智能`|未区分||34.9%|Acemoglu等宽口径|相关度34.9%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_autonomous|`自动驾驶\|无人驾驶\|智能驾驶`|传统AI||11.5%|项目补充|相关度11.5%达到conditional门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_cnn|`CNN`|传统AI||80.3%|项目补充|相关度80.3%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_cv_abbr|`CV`|传统AI||58.7%|项目补充|相关度58.7%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_data_science|`数据科学\|Data Science\|数据挖掘\|Data Mining`|传统AI||42.5%|Acemoglu等宽口径|相关度42.5%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_digital_human|`数字人\|虚拟人`|生成式AI||14.8%|项目补充（生成式）|相关度14.8%达到conditional门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_image_processing_generic|`图像处理\|视觉算法\|图像算法\|Halcon`|传统AI||36.3%|项目补充|相关度36.3%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_llm_names_ambiguous|`Kimi\|Claude\|Gemini\|Cursor`|生成式AI||44.7%|项目补充（生成式）|相关度44.7%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_lora|`LoRA`|生成式AI||91.3%|项目补充（生成式）|相关度91.3%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_ml_abbr|`ML`|传统AI||66.7%|Acemoglu等宽口径|相关度66.7%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_model_training|`模型训练\|训练模型\|算法模型\|智能算法\|AI算法\|算法训练`|未区分||59.1%|Acemoglu等宽口径|相关度59.1%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_prompt|`Prompt`|生成式AI||74.0%|项目补充（生成式）|相关度74.0%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_transformer|`Transformer`|生成式AI||51.4%|项目补充（生成式）|相关度51.4%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|b_tts|`TTS`|传统AI||55.5%|项目补充|相关度55.5%达到strict门槛，但按“只降级不升级”保持宽泛词：相关度在全部含该词的广告上计算，不描述该词单独出现的广告|
|w_超参|`超参`|传统AI|推荐与搜索|97.3%|Word2Vec新增||
|w_artificial_intelligence|`artificial[ _-]?intelligence`|传统AI|机器学习方法;生成式AI;计算机视觉|43.5%|Word2Vec新增||
|w_智能客服|`智能客服`|传统AI|语言与语音|31.1%|Word2Vec新增||
|w_语音交互|`语音交互`|传统AI|语言与语音|24.8%|Word2Vec新增||
|w_问财|`(?<!顾)问财`|传统AI|语言与语音|46.1%|Word2Vec新增||

## 待审词（3个）

|编号|写法|类别|种子组|相关度|来源|v0.2改动|
|---|---|---|---|---:|---|---|
|r_algo_engineer|`算法工程师\|算法研究员\|算法专家`|未区分||52.3%|项目补充||
|r_data_labeling|`数据标注\|AI训练师\|人工智能训练师\|标注员`|未区分||16.9%|项目补充||
|r_smart_generic|`智能化\|智能制造\|智慧城市\|智能家居\|智能硬件`|未区分||2.9%|项目补充||

## 排除规则

同一句里匹配到“排除条件”时，这一句不计该词（不区分大小写）。

|#|适用词条|排除条件|说明|
|---|---|---|---|
|1|b_ai_en、b_ai_tools、b_image_processing_generic|`Photoshop\|Illustrator\|CorelDRAW\|CDR\|InDesign\|C4D\|3D ?Max\|CAD\|(?<![A-Za-z])PS(?![A-Za-z])\|PR[、/,，]\|平面设计\|排版\|美工\|设计软件\|作图软件\|修图`|AI常指Adobe Illustrator设计软件；与PS、CDR等并列出现时不算AI技能|
|2|b_cv_abbr|`简历\|投递\|发送\|邮箱\|resume\|Resume\|附件`|CV常指简历|
|3|g_gpt|`分区\|MBR\|磁盘\|硬盘\|UEFI\|单片机\|MCU\|SPI\|I2C\|PWM\|UART\|定时器\|GPT团队`|GPT在运维语境中可指GUID分区表；MCU语境中GPT指通用定时器|
|4|b_cnn|`新闻\|媒体\|电视\|BBC\|记者`|CNN可指新闻机构|
|5|b_llm_names_ambiguous|`联系人\|HR\|微信\|电话\|先生\|女士\|小姐\|游标\|数据库\|SQL`|Kimi/Claude等可能是人名，Cursor可能指数据库游标|
|6|aahr_sentiment_analysis、aahr_sentiment_classification|`情感咨询\|情感导师\|情感分析师\|婚恋\|恋爱\|挽回\|心理咨询\|情感顾问\|两性`|中文“情感分析师”多为婚恋情感咨询岗位，不是文本情感分析|
|7|x_gan|`射频\|半导体\|功放\|功率\|GaAs\|SiC\|SIC\|工艺\|器件\|芯片\|氮化镓\|外延\|晶圆`|GaN/GAN在射频和功率半导体中指氮化镓|
|8|x_cv_tasks、aahr_object_recognition|`雷达\|毫米波\|信号处理\|门禁\|安防\|监控\|闸机\|考勤\|设备的操作\|弱电`|雷达信号处理中的目标检测/识别，以及安防设备的人脸识别运维，不算AI技能|
|9|b_ai_en|`SMT\|DIP\|插件\|焊接\|贴片\|波峰焊\|AOI`|电子装配中AI指自动插件（Auto Insertion）|
|10|b_llm_bare|`大模型\d?(?:展示\|渲染\|加载\|数据轻量化)\|(?:城市\|BIM\|三维\|3D\|倾斜摄影\|实景)\S{0,3}大模型`|v0.2：单独“大模型”升为严格词；三维模型用法（Web端大模型展示、大模型数据轻量化、城市大模型、BIM大模型等）不算。11-18全样本核对后收窄：不再因同句出现“3D”“三维”“特效”或“大模型建模/轻量化”就排除（误伤“自然语言大模型建模工程师”“大模型轻量化部署”“视觉大模型、3D视觉”）。“场景”“平台”太宽泛，不进排除规则|
|11|g_llm_en|`法学\|法律\|律师\|Master of Laws`|v0.2误判1：LLM指法学硕士（Master of Laws）|
|12|g_prompt_eng|`(?:搜索\|输入)提示词`|v0.2误判2：“搜索提示词”“输入提示词”是搜索框文字|
|13|g_image_gen_tools|`(?<![A-Za-z])(?:PS\|Photoshop\|CDR\|CorelDRAW)\s*[/、，,]\s*AI(?:绘图\|绘画\|作图)`|v0.2误判3：“PS/AI绘图”中的AI指Adobe Illustrator（原设计软件排除规则未覆盖g_image_gen_tools）|
|14|g_finetune、w_微调、w_精调|`^(?!.*(?:大模型\|LLM\|语言模型\|GPT\|AIGC\|深度学习\|神经网络)).*(?:3D\|三维\|建模\|动画\|角色\|贴图)`|v0.2误判4：3D建模、动画岗位里的“模型微调”；同句有大模型/LLM等词时不排除|
|15|g_finetune|`^(?!.*(?:model\|模型\|LLM\|GPT\|BERT\|(?<![a-z])AI(?![a-z])\|神经网络\|深度学习\|transformer\|LoRA\|SFT\|RLHF\|微调\|精调\|训练\|量化\|剪枝\|蒸馏\|推理\|算法\|PyTorch\|TensorFlow\|芯片\|NPU)).*fine-?tun`|v0.2误判5：非AI语境的英文fine-tune（如生产线setup、fine-tuning）；同句有model、LLM、训练、量化、剪枝、蒸馏、算法等词时不排除（11-18全样本核对后补充，避免误伤“针对海思芯片finetune”“fine-tune、剪枝、蒸馏”）|
|16|g_agent|`(?:城市\|园区)智能体`|v0.2误判6：“城市智能体”“园区智能体”是智慧城市产品名|
|17|g_gpt|`GPT\s*会议`|v0.2误判7：“GPT会议”不是技能写法|

## v0.2改动记录

- aahr_machine_vision: strict→conditional（相关度21.3%<30%）
- aahr_lsa: strict→conditional（出现不足30条，默认条件词）
- aahr_lda: strict→conditional（出现不足30条，默认条件词）
- aahr_kernel_methods: strict→conditional（出现不足30条，默认条件词）
- aahr_libsvm: strict→conditional（出现不足30条，默认条件词）
- aahr_sentiment_classification: strict→conditional（出现不足30条，默认条件词）
- aahr_predictive_models: 保持broad（门槛建议broad→conditional，不执行）
- g_image_gen_tools: strict→conditional（相关度21.1%<30%）
- b_ai_zh: 保持broad（门槛建议broad→strict，不执行）
- b_ai_en: 保持broad（门槛建议broad→conditional，不执行）
- b_ml_abbr: 保持broad（门槛建议broad→strict，不执行）
- b_data_science: 保持broad（门槛建议broad→strict，不执行）
- b_model_training: 保持broad（门槛建议broad→strict，不执行）
- b_cv_abbr: 保持broad（门槛建议broad→strict，不执行）
- b_cnn: 保持broad（门槛建议broad→strict，不执行）
- b_image_processing_generic: 保持broad（门槛建议broad→strict，不执行）
- b_autonomous: 保持broad（门槛建议broad→conditional，不执行）
- b_transformer: 保持broad（门槛建议broad→strict，不执行）
- b_lora: 保持broad（门槛建议broad→strict，不执行）
- b_prompt: 保持broad（门槛建议broad→strict，不执行）
- b_llm_names_ambiguous: 保持broad（门槛建议broad→strict，不执行）
- b_digital_human: 保持broad（门槛建议broad→conditional，不执行）
- b_ai_tools: 保持broad（门槛建议broad→strict，不执行）
- b_tts: 保持broad（门槛建议broad→strict，不执行）
- b_ai_major: 保持broad（门槛建议broad→conditional，不执行）
- b_llm_bare: broad→strict（例外），加三维模型排除规则
- 排除规则：v0.2：单独“大模型”升为严格词；三维模型用法（Web端大模型展示、大模型数据轻量化、城市大模型、BIM大模型等）不算。11-18全样本核对后收窄：不再因同句出现“3D”“三维”“特效”或“大模型建模/轻量化”就排除（误伤“自然语言大模型建模工程师”“大模型轻量化部署”“视觉大模型、3D视觉”）。“场景”“平台”太宽泛，不进排除规则
- 排除规则：v0.2误判1：LLM指法学硕士（Master of Laws）
- 排除规则：v0.2误判2：“搜索提示词”“输入提示词”是搜索框文字
- 排除规则：v0.2误判3：“PS/AI绘图”中的AI指Adobe Illustrator（原设计软件排除规则未覆盖g_image_gen_tools）
- 排除规则：v0.2误判4：3D建模、动画岗位里的“模型微调”；同句有大模型/LLM等词时不排除
- 排除规则：v0.2误判5：非AI语境的英文fine-tune（如生产线setup、fine-tuning）；同句有model、LLM、训练、量化、剪枝、蒸馏、算法等词时不排除（11-18全样本核对后补充，避免误伤“针对海思芯片finetune”“fine-tune、剪枝、蒸馏”）
- 排除规则：v0.2误判6：“城市智能体”“园区智能体”是智慧城市产品名
- 排除规则：v0.2误判7：“GPT会议”不是技能写法
- 加入第4步筛选通过的新词187个（source = w2v_expansion）
- 误判4排除规则同时用于新词w_微调、w_精调
## v1.0改动记录（§8微调一轮，2026-11-18）

- 依据：人工分层标注（A、B各205条，重叠50条，有效358条；独立标注kappa 0.527，统一口径后重标kappa 0.855；15条分歧逐条裁定），按标注前写定的§8规则只调一轮
- 规则3：只命中新词层人工判AI比例 pre 0%、post 15%（<50%） → 删除在误判中出现过的Word2Vec新词，共24个：`w_agent`、`w_apriori`、`w_kmeans`、`w_ocr`、`w_pcl`、`w_regression`、`w_sfm`、`w_slam`、`w_vision_pro`、`w_visionmaster`、`w_visionpro`、`w_决策树`、`w_分词`、`w_变化检测`、`w_图像分类`、`w_多模态`、`w_搜索算法`、`w_目标跟踪`、`w_聚类`、`w_自然语言`、`w_训推`、`w_迁移学习`、`w_配准`、`w_降维`
- 规则1：严格版查准率 pre 0.709（<85%；post 0.895） → 误判最多的严格词降一级（严格→条件）：`aahr_image_processing`
  - 38、9、11裁为0后，图像处理与机器学习误判数并列（各4条）；取图像处理：裁定前它是唯一误判最多的词，且降级不损失查全率；机器学习降级会使pre查全率由1.00降至0.81
- 未触发：条件层人工判AI比例0%/7%（<70%），不调门槛
- 报告口径：中期报告以微调前指标为准；同一批样本微调，微调后指标偏乐观，仅供参考
