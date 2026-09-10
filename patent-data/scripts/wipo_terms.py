"""WIPO K1（核心 AI 關鍵詞）與 K2（泛用關鍵詞）的結構化編碼。

逐字對應 config/wipo_search_strings_verbatim.txt 的 Block 2 (K1) 與 Block 3 (K2)。
每一項後面的註解即為 WIPO 原文，方便逐條核對。
"""

from wipo_keywords import Term

# ---------------------------------------------------------------- K1
K1 = [
    Term([["artific+", "computation+"], ["intelligen+"]], [1]),  # ((ARTIFIC+ OR COMPUTATION+) 1W INTELLIGEN+)
    Term([["neural"], ["network+"]], [1]),                       # (NEURAL 1W NETWORK+)
    Term(["neural_network+"]),                                   # NEURAL_NETWORK+ / NEURAL-NETWORK+
    Term([["bayes+"], ["network+"]], [1]),                       # (BAYES+ 1W NETWORK+)
    Term(["bayesian-network+"]),                                 # BAYESIAN-NETWORK+ / BAYESIAN_NETWORK+
    Term(["chatbot?"]),                                          # (CHATBOT?)
    Term([["data"], ["mining+"]], [1]),                          # (DATA 1W MINING+)
    Term([["decision"], ["model?"]], [1]),                       # (DECISION 1W MODEL?)
    Term([["deep"], ["learning+"]], [1]),                        # (DEEP 1W LEARNING+)
    Term(["deep-learning+"]),                                    # DEEP-LEARNING+ / DEEP_LEARNING+
    Term([["genetic"], ["algorithm?"]], [1]),                    # (GENETIC 1W ALGORITHM?)
    Term([["inductive"], ["logic"], ["programm+"]], [1, 1]),     # ((INDUCTIVE 1W LOGIC) 1D PROGRAMM+)
    Term([["machine"], ["learning+"]], [1]),                     # (MACHINE 1W LEARNING+)
    Term(["machine-learning+"]),                                 # MACHINE_LEARNING+ / MACHINE-LEARNING+
    Term([["natural"], ["language"], ["generation", "processing"]], [1, 1]),
    #                                     ((NATURAL 1D LANGUAGE) 1W (GENERATION OR PROCESSING))
    Term([["reinforcement"], ["learning"]], [1]),                # (REINFORCEMENT 1W LEARNING)
    Term([["supervised"], ["learning+", "training"]], [1]),      # (SUPERVISED 1W (LEARNING+ OR TRAINING))
    Term(["supervised-learning+"]),                              # SUPERVISED-LEARNING+ / SUPERVISED_LEARNING+
    Term([["swarm"], ["intelligen+"]], [1]),                     # (SWARM 1W INTELLIGEN+)
    Term(["swarm-intelligen+"]),                                 # SWARM-INTELLIGEN+ / SWARM_INTELLIGEN+
    Term([["unsupervised"], ["learning+", "training"]], [1]),    # (UNSUPERVISED 1W (LEARNING+ OR TRAINING))
    Term(["unsupervised-learning+"]),                            # UNSUPERVISED-LEARNING+ / UNSUPERVISED_LEARNING+
    Term([["semi-supervised"], ["learning+", "training"]], [1]),  # (SEMI-SUPERVISED 1W (LEARNING+ OR TRAINING))
    Term(["semi-supervised-learning+"]),                         # SEMI-SUPERVISED-LEARNING / SEMI_SUPERVISED_LEARNING+
    Term(["connectionis#"]),                                     # CONNECTIONIS#
    Term([["expert"], ["system?"]], [1]),                        # (EXPERT 1W SYSTEM?)
    Term([["fuzzy"], ["logic?"]], [1]),                          # (FUZZY 1W LOGIC?)
    Term(["transfer-learning"]),                                 # TRANSFER-LEARNING / TRANSFER_LEARNING
    Term([["transfer"], ["learning"]], [1]),                     # (TRANSFER 1W LEARNING)
    Term([["learning"], ["algorithm?"]], [3]),                   # (LEARNING 3W ALGORITHM?)
    Term([["learning"], ["model?"]], [1]),                       # (LEARNING 1W MODEL?)
    Term(["support vector machine?"]),                           # (SUPPORT VECTOR MACHINE?)
    Term(["random forest?"]),                                    # (RANDOM FOREST?)
    Term(["decision tree?"]),                                    # (DECISION TREE?)
    Term(["gradient tree boosting"]),                            # (GRADIENT TREE BOOSTING)
    Term(["xgboost"]),                                           # (XGBOOST)
    Term(["adaboost"]),                                          # ADABOOST
    Term(["rankboost"]),                                         # RANKBOOST
    Term(["logistic regression"]),                               # (LOGISTIC REGRESSION)
    Term(["stochastic gradient descent"]),                       # (STOCHASTIC GRADIENT DESCENT)
    Term(["multilayer perceptron?"]),                            # (MULTILAYER PERCEPTRON?)
    Term(["latent semantic analysis"]),                          # (LATENT SEMANTIC ANALYSIS)
    Term(["latent dirichlet allocation"]),                       # (LATENT DIRICHLET ALLOCATION)
    Term(["multi-agent system?"]),                               # (MULTI-AGENT SYSTEM?)
    Term(["hidden markov model?"]),                              # (HIDDEN MARKOV MODEL?)
]

# ---------------------------------------------------------------- K2
K2 = [
    Term(["clustering"]),                                        # CLUSTERING
    Term(["comput+ creativity"]),                                # (COMPUT+ CREATIVITY)
    Term(["descriptive model?"]),                                # (DESCRIPTIVE MODEL?)
    Term(["inductive reasoning"]),                               # (INDUCTIVE REASONING)
    Term(["overfitting"]),                                       # OVERFITTING
    Term([["predictive"], ["analytics", "model?"]], [1]),        # (PREDICTIVE 1W (ANALYTICS OR MODEL?))
    Term([["target"], ["function?"]], [1]),                      # (TARGET 1W FUNCTION?)
    Term([["test", "training", "validation"], ["data"], ["set?"]], [1, 1]),
    #                                     ((TEST OR TRAINING OR VALIDATION) 1D DATA 1D SET?)
    Term(["backpropagation?"]),                                  # BACKPROPAGATION?
    Term(["self-learning"]),                                     # SELF-LEARNING / SELF_LEARNING
    Term(["objective function?"]),                               # (OBJECTIVE FUNCTION?)
    Term(["feature? selection"]),                                # (FEATURE? SELECTION)
    Term(["embedding?"]),                                        # (EMBEDDING?)
    Term(["active learning"]),                                   # (ACTIVE LEARNING)
    Term(["regression model?"]),                                 # (REGRESSION MODEL?)
    Term([["stochastic", "probabilist+"],
          ["approach+", "technique?", "method?", "algorithm?"]], [2], ordered=False),
    #             ((STOCHASTIC OR PROBABILIST+) 2D (APPROACH+ OR TECHNIQUE? OR METHOD? OR ALGORITHM?))
    Term([["recommend+"], ["system?"]], [0]),                    # (RECOMMEND+ SYSTEM?)
    Term([["text", "speech", "hand_writing", "facial", "face?", "character?"],
          ["analysis", "analytic?", "recognition"]], [1]),
    #   ((TEXT OR SPEECH OR HAND_WRITING OR FACIAL OR FACE? OR CHARACTER?) 1W (ANALYSIS OR ANALYTIC? OR RECOGNITION))
]
