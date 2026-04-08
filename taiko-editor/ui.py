"""
Minimal UI library for Pygame.
"""
import pygame

class UIElement:
    def __init__(self, x, y, w, h):
        self.rect = pygame.Rect(x, y, w, h)
        self.visible = True

    def handle_event(self, event):
        pass

    def draw(self, surface):
        pass

class Button(UIElement):
    def __init__(self, x, y, w, h, text, callback, color=(60, 60, 60), hover_color=(80, 80, 80)):
        super().__init__(x, y, w, h)
        self.text = text
        self.callback = callback
        self.color = color
        self.hover_color = hover_color
        self.is_hovered = False
        self.font = pygame.font.SysFont("Arial", 16)

    def handle_event(self, event):
        if not self.visible: return
        if event.type == pygame.MOUSEMOTION:
            self.is_hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and self.is_hovered:
                self.callback()

    def draw(self, surface):
        if not self.visible: return
        color = self.hover_color if self.is_hovered else self.color
        pygame.draw.rect(surface, color, self.rect, border_radius=4)
        pygame.draw.rect(surface, (200, 200, 200), self.rect, 1, border_radius=4)
        
        txt_surf = self.font.render(self.text, True, (255, 255, 255))
        txt_rect = txt_surf.get_rect(center=self.rect.center)
        surface.blit(txt_surf, txt_rect)

class Label(UIElement):
    def __init__(self, x, y, text, font_size=20, color=(255, 255, 255)):
        super().__init__(x, y, 0, 0)
        self.text = text
        self.color = color
        self.font = pygame.font.SysFont("Arial", font_size)

    def draw(self, surface):
        if not self.visible: return
        txt_surf = self.font.render(self.text, True, self.color)
        surface.blit(txt_surf, (self.rect.x, self.rect.y))

class TextInput(UIElement):
    def __init__(self, x, y, w, h, initial_text="", on_change=None):
        super().__init__(x, y, w, h)
        self.text = initial_text
        self.active = False
        self.on_change = on_change
        self.font = pygame.font.SysFont("Arial", 16)
        self.color_inactive = (50, 50, 50)
        self.color_active = (70, 70, 90)

    def handle_event(self, event):
        if not self.visible: return
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_RETURN:
                self.active = False
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            else:
                self.text += event.unicode
            if self.on_change:
                self.on_change(self.text)

    def draw(self, surface):
        if not self.visible: return
        color = self.color_active if self.active else self.color_inactive
        pygame.draw.rect(surface, color, self.rect, border_radius=2)
        pygame.draw.rect(surface, (100, 100, 100) if not self.active else (200, 200, 255), self.rect, 1, border_radius=2)
        
        txt_surf = self.font.render(self.text, True, (255, 255, 255))
        # Clip or scroll if too long? basic for now
        surface.blit(txt_surf, (self.rect.x + 5, self.rect.centery - txt_surf.get_height()//2))
