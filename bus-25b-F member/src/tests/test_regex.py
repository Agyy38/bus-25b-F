import unittest
from regex_rules import parse_period, parse_stop, parse_dom, STATION, PLATE, SPEED


class RegexTests(unittest.TestCase):
    def test_period_normal(self):
        result = parse_period("2026年3月25日<br>10:00开始 至<br>2026年12月8日<br>尾班车")
        self.assertEqual(result, {"start_date": "2026年3月25日", "start_time": "10:00",
                                  "end_date": "2026年12月8日", "end_time": "尾班车"})

    def test_period_missing_time(self):
        result = parse_period("2026年3月25日開始至2026年12月8日尾班車")
        self.assertIsNone(result["start_time"])

    def test_period_html_variants(self):
        for br in ("<br>", "<br/>", "<BR />", "  \n"):
            with self.subTest(br=br):
                self.assertEqual(parse_period(f"2026年03月25日{br}10:00开始至2026年12月08日{br}23:00")["end_time"], "23:00")

    def test_invalid_calendar_and_time(self):
        for text in ("2026年2月30日开始至2026年12月8日", "2026年3月25日99:99开始至2026年12月8日", "", "{{:period}}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_period(text)

    def test_stop_name_spaces(self):
        self.assertEqual(parse_stop(" T324/2 澳门运动场 临时站 "), {"code": "T324/2", "name": "澳门运动场 临时站"})

    def test_stop_missing_name(self):
        for text in ("M12", "M12 ", "X12 名称"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_stop(text)

    def test_dom_multiple_buses_and_stations(self):
        result = parse_dom("25B T560/2-横琴澳方口岸 AB1234 32 km/h AB5678 T372-莲花路 M1-总站 CD1234 0 km/h")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "横琴澳方口岸")
        self.assertEqual(result[0]["buses"], [{"plate": "AB1234", "speed": "32"}, {"plate": "AB5678", "speed": None}])
        self.assertEqual(result[1]["buses"], [])
        self.assertEqual(result[2]["buses"][0]["speed"], "0")

    def test_field_full_match(self):
        for pattern, yes, no in ((STATION, "M61/2", "M61/2junk"), (PLATE, "AB1234", "AB12345"), (SPEED, "0", "12km/h")):
            with self.subTest(pattern=pattern):
                self.assertIsNotNone(pattern.fullmatch(yes))
                self.assertIsNone(pattern.fullmatch(no))

    def test_c_station_documented_as_review(self):
        self.assertIsNone(STATION.fullmatch("C700"))
        self.assertEqual(parse_stop("C700 口岸")["code"], "C700")


if __name__ == "__main__":
    unittest.main()
