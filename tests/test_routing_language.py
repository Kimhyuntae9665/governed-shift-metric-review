import unittest
from metric_review.routing import route_keyword,route_model

class LanguageRegressionTests(unittest.TestCase):
 def test_screen_terms_and_korean_particles(self):
  for query,metric,scope in [
   ('교대 A 양품률을 보여줘','quality','A'),
   ('교대 A 종합 설비 효율을 보여줘','oee','A'),
   ('교대 B의 품질률을 보여줘','quality','B'),
   ('A교대의 OEE를 보여줘','oee','A'),
   ('교대 A와 B OEE','oee','combined'),
   ('A와 B 교대 OEE','oee','combined')]:
   with self.subTest(query=query):
    out=route_keyword(query,['PLANT-A'],'PLANT-A')
    self.assertEqual((out['action'],out['metric_id'],out['scope']),('calculate',metric,scope))
 def test_excluded_shift_never_becomes_combined(self):
  for query,scope in [('교대 B를 제외한 OEE를 보여줘','A'),('B교대를 제외한 OEE','A'),('교대 A를 제외한 양품률','B'),('OEE excluding shift B','A')]:
   with self.subTest(query=query):
    self.assertEqual(route_keyword(query,['PLANT-A'],'PLANT-A')['scope'],scope)
 def test_ambiguous_scope_is_clarified_before_model(self):
  # No llm module import is needed: unsupported scopes must stop before transport.
  for query in ['교대 B를 제외하지 말고 OEE','교대 B를 제외하면 안 되는 OEE','교대 A를 제외하면 안 돼 OEE','교대 B 빼면 안돼 OEE','교대 B 제외 금지 OEE','교대 A와 교대 B를 제외한 OEE','B를 제외한 OEE','교대 C OEE','OEE without night shift']:
   with self.subTest(query=query):
    out=route_keyword(query,['PLANT-A'],'PLANT-A')
    self.assertEqual((out['action'],out['scope']),('clarify',None))
    out=route_model(query,['PLANT-A'],'PLANT-A')
    self.assertEqual(out['action'],'clarify')
    self.assertFalse(out['model_requested'])
 def test_authorization_guard_still_precedes_scope(self):
  with self.assertRaises(PermissionError):route_keyword('PLANT-SECRET 교대 B 제외 OEE',['PLANT-A'],'PLANT-A')

if __name__=='__main__':unittest.main()
