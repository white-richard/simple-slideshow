import math
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pygame
from PIL import Image, ImageDraw, ImageFilter, ImageFont


@dataclass
class Config:
    photos_dir: Path = field(default_factory=lambda: Path("photos"))  # Directory containing images
    rotation_seconds: float = 10
    shuffle: bool = True
    transition_duration: float = 0.8
    caption_font_size: int = 64
    background_blur_radius: int = 30
    supported_ext: frozenset = field(
        default_factory=lambda: frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"})
    )


def scan_photos(config: Config) -> list[Path]:
    """Return a sorted list of Paths for supported images."""
    directory = config.photos_dir
    if not directory.is_dir():
        print(f"[ERROR] Photos directory not found: {directory!r}")
        sys.exit(1)
    paths = [p for p in directory.iterdir() if p.suffix.lower() in config.supported_ext]
    if not paths:
        print(f"[ERROR] No supported images found in {directory!r}")
        sys.exit(1)
    return sorted(paths)


def caption_from_path(path: Path) -> str:
    """Derive a human-friendly caption from a file path."""
    stem = path.stem.lstrip("$")
    return stem.replace("_", " ").replace("-", " ")


def pil_to_surface(img: Image.Image) -> pygame.Surface:
    """Convert a PIL RGBA image to a pygame Surface."""
    raw = img.tobytes("raw", "RGBA")
    return pygame.image.fromstring(raw, img.size, "RGBA")


def fit_image(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Scale PIL image to fit target dimensions, preserving aspect ratio."""
    img_w, img_h = img.size
    scale = min(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


def build_background(
    img: Image.Image, screen_w: int, screen_h: int, blur_radius: int
) -> Image.Image:
    """Create a blurred, darkened version of img stretched to screen size."""
    bg = img.convert("RGB").resize((screen_w, screen_h), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    overlay = Image.new("RGB", (screen_w, screen_h), (0, 0, 0))
    bg = Image.blend(bg, overlay, alpha=0.45)
    return bg.convert("RGBA")


def build_caption_surface(text: str, screen_w: int, font_size: int) -> pygame.Surface:
    """Render caption as a full-width frosted bar flush to the bottom."""
    pad_y = 18

    font_candidates = [
        str(Path(__file__).parent / "fonts" / "IBMPlexSans-Bold.ttf"),
        "IBMPlexSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    pil_font = None
    for candidate in font_candidates:
        try:
            pil_font = ImageFont.truetype(candidate, font_size)
            break
        except OSError:
            continue
    if pil_font is None:
        pil_font = ImageFont.load_default()

    dummy = Image.new("RGBA", (1, 1))
    bbox = ImageDraw.Draw(dummy).textbbox((0, 0), text, font=pil_font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    bar_h = text_h + pad_y * 2
    # bar = Image.new("RGBA", (screen_w, bar_h), (18, 18, 28, 210))
    bar = Image.new("RGBA", (screen_w, bar_h), (40, 28, 16, 160))

    # Subtle 1px lighter top edge to separate bar from image
    bar.paste(Image.new("RGBA", (screen_w, 1), (255, 255, 255, 30)), (0, 0))

    draw = ImageDraw.Draw(bar)
    text_x = (screen_w - text_w) // 2 - bbox[0]
    text_y = pad_y - bbox[1]
    draw.text((text_x + 1, text_y + 1), text, font=pil_font, fill=(0, 0, 0, 90))  # shadow
    draw.text((text_x, text_y), text, font=pil_font, fill=(255, 255, 255, 245))

    return pil_to_surface(bar)


class Slide:
    def __init__(self, path: Path, screen_w: int, screen_h: int, config: Config):
        self.path = path
        self.caption = caption_from_path(path)

        pil_img = Image.open(path).convert("RGBA")

        # Background layer
        bg_pil = build_background(pil_img, screen_w, screen_h, config.background_blur_radius)
        self.background = pil_to_surface(bg_pil)

        # Foreground (fitted) layer
        fg_pil = fit_image(pil_img, screen_w, screen_h)
        self.foreground = pil_to_surface(fg_pil)
        self.fg_rect = self.foreground.get_rect(center=(screen_w // 2, screen_h // 2))

        # Caption — only rendered when the filename starts with '$'
        if path.name.startswith("$"):
            self.caption_surf = build_caption_surface(
                self.caption, screen_w, config.caption_font_size
            )
            cap_rect = self.caption_surf.get_rect()
            self.cap_x = (screen_w - cap_rect.width) // 2
            self.cap_y = screen_h - cap_rect.height - 40
        else:
            self.caption_surf = None
            self.cap_x = 0
            self.cap_y = 0


class Slideshow:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()

        pygame.init()
        pygame.display.set_caption("Slideshow")

        info = pygame.display.Info()
        self.screen_w, self.screen_h = info.current_w, info.current_h
        self.fullscreen = True
        self.screen = pygame.display.set_mode((self.screen_w, self.screen_h), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)

        self.clock = pygame.time.Clock()

        # Image list
        all_paths = scan_photos(self.config)
        if self.config.shuffle:
            random.shuffle(all_paths)
        self.paths = all_paths
        self.index = 0

        # State
        self.paused = False
        self.running = True

        # Transition state
        self.transitioning = False
        self.transition_start = 0.0
        self.current_slide: Slide | None = None
        self.next_slide: Slide | None = None
        self.alpha = 255  # alpha of current slide (255 = fully visible)

        # Slide timer
        self.slide_start = time.time()

        # Load first slide
        self.current_slide = self._load_slide(self.index)
        # Pre-load next in background
        self._preload_thread: threading.Thread | None = None
        self._preloaded: Slide | None = None
        self._start_preload(self._next_index())

    def _next_index(self, step: int = 1) -> int:
        return (self.index + step) % len(self.paths)

    def _prev_index(self) -> int:
        return (self.index - 1) % len(self.paths)

    def _load_slide(self, idx: int) -> Slide | None:
        path = self.paths[idx]
        try:
            return Slide(path, self.screen_w, self.screen_h, self.config)
        except OSError:
            print(f"[WARN] Could not load image, skipping: {path}")
            self.paths.pop(idx)
            return None

    def _start_preload(self, idx: int):
        def _load():
            if idx < len(self.paths):
                self._preloaded = self._load_slide(idx)

        self._preload_thread = threading.Thread(target=_load, daemon=True)
        self._preload_thread.start()

    def _get_preloaded(self, expected_idx: int) -> Slide | None:
        """Return preloaded slide if it matches, else load synchronously."""
        if self._preload_thread:
            self._preload_thread.join(timeout=5)
        if self._preloaded is not None:
            return self._preloaded
        if expected_idx < len(self.paths):
            return self._load_slide(expected_idx)
        return None

    def _begin_transition(self, target_index: int):
        """Start a crossfade to the slide at target_index."""
        if self.transitioning:
            return
        if not self.paths:
            print("[ERROR] No images remaining.")
            self.running = False
            return

        next_idx = target_index % len(self.paths)
        if next_idx == self._next_index():
            next_slide = self._get_preloaded(next_idx)
        else:
            next_slide = self._load_slide(next_idx)

        # If the slide failed to load, skip ahead to the next one
        if next_slide is None:
            self._begin_transition(next_idx)
            return

        self.next_slide = next_slide
        self.transitioning = True
        self.transition_start = time.time()
        self.alpha = 255

        # Queue up next preload
        self._preloaded = None
        self._start_preload((next_idx + 1) % len(self.paths))

    def _finish_transition(self):
        self.current_slide = self.next_slide
        self.next_slide = None
        self.transitioning = False
        self.alpha = 255
        self.index = self.paths.index(self.current_slide.path)  # type: ignore[union-attr]
        self.slide_start = time.time()

    def run(self):
        while self.running:
            dt = self.clock.tick(60) / 1000.0

            self._handle_events()
            self._update(dt)
            self._draw()

        pygame.quit()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                key = event.key

                if key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False

                elif key in (pygame.K_RIGHT, pygame.K_SPACE):
                    self._advance(+1)

                elif key == pygame.K_LEFT:
                    self._advance(-1)

                elif key == pygame.K_p:
                    self.paused = not self.paused
                    if not self.paused:
                        self.slide_start = time.time()  # reset timer on resume

                elif key == pygame.K_f:
                    self._toggle_fullscreen()

    def _advance(self, direction: int):
        if self.transitioning:
            # Jump immediately to destination
            self._finish_transition()
        target = self._next_index() if direction > 0 else self._prev_index()
        self._begin_transition(target)

    def _toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode((self.screen_w, self.screen_h), pygame.FULLSCREEN)
            pygame.mouse.set_visible(False)
        else:
            self.screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
            pygame.mouse.set_visible(True)

    def _update(self, dt: float):
        now = time.time()

        # Auto-advance
        if (
            not self.paused
            and not self.transitioning
            and (now - self.slide_start) >= self.config.rotation_seconds
        ):
            self._begin_transition(self._next_index())

        # Progress transition
        if self.transitioning:
            elapsed = now - self.transition_start
            progress = min(elapsed / self.config.transition_duration, 1.0)
            # Ease in-out (sine)
            eased = (1 - math.cos(progress * math.pi)) / 2
            self.alpha = int(255 * (1 - eased))

            if progress >= 1.0:
                self._finish_transition()

    def _draw(self):
        sw, sh = self.screen.get_size()
        self.screen.fill((0, 0, 0))

        if self.current_slide:
            self._draw_slide(self.current_slide, self.alpha if self.transitioning else 255, sw, sh)

        if self.transitioning and self.next_slide:
            next_alpha = 255 - self.alpha
            self._draw_slide(self.next_slide, next_alpha, sw, sh)

        pygame.display.flip()

    def _draw_slide(self, slide: Slide, alpha: int, sw: int, sh: int):
        """Blit background, foreground, and caption with given alpha."""
        tmp = pygame.Surface((sw, sh), pygame.SRCALPHA)

        # Background
        bg = slide.background.copy()
        bg_scaled = pygame.transform.scale(bg, (sw, sh)) if bg.get_size() != (sw, sh) else bg
        tmp.blit(bg_scaled, (0, 0))

        # Foreground (centered)
        fg_rect = slide.foreground.get_rect(center=(sw // 2, sh // 2))
        tmp.blit(slide.foreground, fg_rect)

        # Caption (only present when filename starts with '$')
        if slide.caption_surf is not None:
            cap_y = sh - slide.caption_surf.get_height()
            tmp.blit(slide.caption_surf, (0, cap_y))

        # Apply alpha to entire surface
        tmp.set_alpha(alpha)
        self.screen.blit(tmp, (0, 0))


if __name__ == "__main__":
    app = Slideshow()
    app.run()
