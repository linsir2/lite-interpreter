# Generated from src/kag/compiler/grammar/KnowledgeSpec.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .KnowledgeSpecParser import KnowledgeSpecParser
else:
    from KnowledgeSpecParser import KnowledgeSpecParser

# This class defines a complete listener for a parse tree produced by KnowledgeSpecParser.
class KnowledgeSpecListener(ParseTreeListener):

    # Enter a parse tree produced by KnowledgeSpecParser#spec.
    def enterSpec(self, ctx:KnowledgeSpecParser.SpecContext):
        pass

    # Exit a parse tree produced by KnowledgeSpecParser#spec.
    def exitSpec(self, ctx:KnowledgeSpecParser.SpecContext):
        pass


    # Enter a parse tree produced by KnowledgeSpecParser#ruleSpec.
    def enterRuleSpec(self, ctx:KnowledgeSpecParser.RuleSpecContext):
        pass

    # Exit a parse tree produced by KnowledgeSpecParser#ruleSpec.
    def exitRuleSpec(self, ctx:KnowledgeSpecParser.RuleSpecContext):
        pass


    # Enter a parse tree produced by KnowledgeSpecParser#metricSpec.
    def enterMetricSpec(self, ctx:KnowledgeSpecParser.MetricSpecContext):
        pass

    # Exit a parse tree produced by KnowledgeSpecParser#metricSpec.
    def exitMetricSpec(self, ctx:KnowledgeSpecParser.MetricSpecContext):
        pass


    # Enter a parse tree produced by KnowledgeSpecParser#filterSpec.
    def enterFilterSpec(self, ctx:KnowledgeSpecParser.FilterSpecContext):
        pass

    # Exit a parse tree produced by KnowledgeSpecParser#filterSpec.
    def exitFilterSpec(self, ctx:KnowledgeSpecParser.FilterSpecContext):
        pass


    # Enter a parse tree produced by KnowledgeSpecParser#pair.
    def enterPair(self, ctx:KnowledgeSpecParser.PairContext):
        pass

    # Exit a parse tree produced by KnowledgeSpecParser#pair.
    def exitPair(self, ctx:KnowledgeSpecParser.PairContext):
        pass


    # Enter a parse tree produced by KnowledgeSpecParser#scalar.
    def enterScalar(self, ctx:KnowledgeSpecParser.ScalarContext):
        pass

    # Exit a parse tree produced by KnowledgeSpecParser#scalar.
    def exitScalar(self, ctx:KnowledgeSpecParser.ScalarContext):
        pass



del KnowledgeSpecParser