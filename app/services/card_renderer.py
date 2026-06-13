from datetime import date
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


class CardRenderer:
    size = (1080, 1920)

    def render_cards(self, brief_payload: dict, output_dir: Path) -> list[dict]:
        today = date.today().isoformat()
        sources = brief_payload["script"]["sources"]
        source_label = "Sources: " + ", ".join(f"S{index}" for index, _ in enumerate(sources, start=1))
        top_post = brief_payload["ranked_posts"][0] if brief_payload["ranked_posts"] else {}
        verdicts = sorted({item["verdict"] for item in brief_payload["fact_checks"]}) or ["unclear"]
        cards = [
            ("cover.png", "Daily Truth Brief", brief_payload["title"], source_label),
            ("card_01_topic.png", "Topic Focus", top_post.get("summary", "No topic summary available."), source_label),
            ("card_02_fact_check.png", "Fact Check", "Verdicts: " + " / ".join(verdicts), source_label),
            ("card_03_timeline.png", "Timeline", self._timeline_text(brief_payload), source_label),
            ("card_04_sources.png", "Sources", self._sources_text(sources), "Keep links in the final description."),
        ]
        rendered = []
        for filename, heading, body, footer in cards:
            path = output_dir / filename
            self._render_card(path, heading, body, footer, today)
            rendered.append(
                {
                    "filename": filename,
                    "path": str(path),
                    "label": "信息整理卡 / AI 生成示意图",
                    "scene_type": "information_card",
                }
            )
        return rendered

    def _render_card(self, path: Path, heading: str, body: str, footer: str, today: str) -> None:
        image = Image.new("RGB", self.size, (248, 249, 250))
        draw = ImageDraw.Draw(image)
        title_font = self._font(70)
        heading_font = self._font(54)
        body_font = self._font(42)
        small_font = self._font(30)
        draw.rectangle((0, 0, self.size[0], 180), fill=(32, 33, 36))
        draw.text((64, 54), "Daily Truth Brief", fill=(255, 255, 255), font=title_font)
        draw.text((64, 220), heading, fill=(22, 90, 160), font=heading_font)
        y = 330
        for line in self._wrap(body, 22):
            draw.text((64, y), line, fill=(32, 33, 36), font=body_font)
            y += 62
        draw.rectangle((64, 1420, 1016, 1700), outline=(218, 220, 224), width=3)
        draw.text((96, 1460), "信息整理卡 / AI 生成示意图", fill=(179, 38, 30), font=body_font)
        draw.text((96, 1540), "No fake screenshot. No voice clone. No auto publish.", fill=(95, 99, 104), font=small_font)
        draw.text((64, 1760), today, fill=(95, 99, 104), font=small_font)
        draw.text((64, 1810), footer[:90], fill=(95, 99, 104), font=small_font)
        image.save(path, "PNG")

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _wrap(self, text: str, width: int) -> list[str]:
        lines: list[str] = []
        for paragraph in str(text).splitlines() or [str(text)]:
            lines.extend(wrap(paragraph, width=width) or [""])
        return lines[:13]

    def _timeline_text(self, brief_payload: dict) -> str:
        return "\n".join(
            f"{index}. {post.get('topic', 'topic')} - {post.get('published_at', '')[:10]}"
            for index, post in enumerate(brief_payload["ranked_posts"], start=1)
        )

    def _sources_text(self, sources: list[dict]) -> str:
        return "\n".join(f"S{index}: {source.get('url', '')}" for index, source in enumerate(sources, start=1))

