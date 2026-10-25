import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from main_cloud_full_echo import ensure_nest_catalog


def box(name,x=520,y=280):
    return SimpleNamespace(name=name,x=x,y=y)


class CatalogTests(unittest.TestCase):
    def run_case(self, pages, tabs):
        clock=[0]
        task=SimpleNamespace(next_frame=Mock(),sleep=Mock(),click=Mock(),log_info=Mock())
        task.ocr=Mock(side_effect=lambda *r:pages() if r[0]==.35 else tabs())
        def tick():
            clock[0]+=.2
            return clock[0]
        with patch('main_cloud_full_echo.time.monotonic',side_effect=tick):
            ensure_nest_catalog(task)
        return task

    def test_ready_catalog_needs_no_click(self):
        t=self.run_case(lambda:[box('测试残象聚落'),box('0/48')],lambda:[])
        t.click.assert_not_called()

    def test_delayed_catalog_waits_without_click(self):
        n=[0]
        def pages():
            n[0]+=1
            return [] if n[0]<4 else [box('测试残象聚落'),box('48/48')]
        t=self.run_case(pages,lambda:[])
        t.click.assert_not_called()

    def test_known_material_page_tab_corrected_once(self):
        n=[0]
        def tabs():
            n[0]+=1
            return [box('素材获取',72,34),box('残象聚落',200,588)]
        t=self.run_case(lambda:[] if n[0]<2 else [box('测试残象聚落'),box('0/41')],tabs)
        t.click.assert_called_once()
        self.assertEqual(t.click.call_args.args[0].name,'残象聚落')

    def test_unknown_page_is_not_clicked(self):
        with self.assertRaisesRegex(RuntimeError,'not positively identified'):
            self.run_case(lambda:[],lambda:[box('残象聚落',200,588)])

    def test_changed_or_duplicate_tab_is_rejected(self):
        n=[0]
        def changed():
            n[0]+=1
            return [box('素材获取'),box('残象聚落',200,588 if n[0]==1 else 530)]
        with self.assertRaisesRegex(RuntimeError,'not positively identified'):
            self.run_case(lambda:[],changed)
        with self.assertRaisesRegex(RuntimeError,'not positively identified'):
            self.run_case(lambda:[],lambda:[box('素材获取'),box('残象聚落',200,588),box('残象聚落',220,590)])

    def test_missing_rows_after_one_click_still_stop(self):
        with self.assertRaisesRegex(RuntimeError,'after one verified'):
            self.run_case(lambda:[],lambda:[box('素材获取'),box('残象聚落',200,588)])

    def test_material_counts_are_not_catalog_proof(self):
        with self.assertRaisesRegex(RuntimeError,'not positively identified'):
            self.run_case(lambda:[box('技能升级材料'),box('0/3'),box('0/48')],lambda:[])


if __name__=='__main__':unittest.main()
