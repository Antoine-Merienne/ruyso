"""
The Dashboard tab's left tool bar.

A narrow strip of icon buttons down the left edge of the canvas, so the
four things you do to assemble a report -- drop a title, a text box or a
shape, and arrange what is there -- are one click away instead of two
levels into a menu bar. "Shape" and "Arrange" drop the very menus the
canvas right-click offers (:mod:`ui.dashboard_menus`), so the two routes
cannot list different commands.

The icons are painted here rather than shipped as assets: they are four
simple glyphs, and drawing them from :mod:`ui.theme`'s text colour means
they follow a live theme switch (:meth:`DashboardTools.apply_theme`)
instead of staying the colour they were exported at.

``page`` is duck-typed (a :class:`ui.dashboard_page.DashboardPage`):
the page owns this widget, so importing it back would be a cycle.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QToolButton, QVBoxLayout, QWidget

from ruyso_app.ui import theme
from ruyso_app.ui.dashboard_menus import fill_arrange_menu, fill_shape_menu

#: Logical size of a painted icon, and of the button around it.
ICON_SIZE = 22
BUTTON_SIZE = 34

#: Tooltip shown on the Arrange button while nothing is selected -- the
#: commands act on a selection, so the button is disabled rather than
#: offering a menu where every entry would quietly do nothing.
_ARRANGE_EMPTY_HINT = "Arrange (select a block first)"


def _pen(painter: QPainter, colour: QColor, width: float = 1.6) -> None:
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)


def _draw_title(painter: QPainter, colour: QColor) -> None:
    """A serif-less capital T."""
    _pen(painter, colour, 2.0)
    painter.drawLine(QPointF(5, 6), QPointF(19, 6))
    painter.drawLine(QPointF(12, 6), QPointF(12, 19))


def _draw_text_box(painter: QPainter, colour: QColor) -> None:
    """A box with two lines of text in it."""
    _pen(painter, colour)
    painter.drawRoundedRect(QRectF(3.5, 5.5, 17, 13), 2.5, 2.5)
    painter.drawLine(QPointF(6.5, 10), QPointF(17.5, 10))
    painter.drawLine(QPointF(6.5, 14), QPointF(13.5, 14))


def _draw_shape(painter: QPainter, colour: QColor) -> None:
    """A square and a circle, overlapping."""
    _pen(painter, colour)
    painter.drawRect(QRectF(3.5, 9.5, 10, 9))
    painter.drawEllipse(QPointF(15.0, 9.5), 5.0, 5.0)


def _draw_arrange(painter: QPainter, colour: QColor) -> None:
    """Three left-aligned bars -- the align/distribute glyph."""
    _pen(painter, colour, 2.0)
    painter.drawLine(QPointF(4, 6), QPointF(19, 6))
    painter.drawLine(QPointF(4, 12), QPointF(14, 12))
    painter.drawLine(QPointF(4, 18), QPointF(17, 18))


#: Glyphs are painted at twice their logical size and tagged with that
#: ratio, so they stay crisp on a retina screen without asking the
#: widget (which has no screen yet while the tool bar is being built).
_ICON_SCALE = 2.0

#: The square the ``_draw_*`` functions above lay their glyph out on.
_GLYPH_GRID = 24.0


def make_icon(
    draw: Callable[[QPainter, QColor], None],
    colour: QColor,
    size: int = ICON_SIZE,
) -> QIcon:
    """
    Paint one glyph into an icon ``size`` logical pixels square.

    The pixmap carries a device pixel ratio, and QPainter already
    accounts for that -- so the only scaling applied here is the glyph
    grid onto the logical size. Scaling by the ratio as well draws the
    glyph at twice the size and the icon comes out cropped to its
    top-left corner.
    """
    pixmap = QPixmap(int(size * _ICON_SCALE), int(size * _ICON_SCALE))
    pixmap.setDevicePixelRatio(_ICON_SCALE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size / _GLYPH_GRID, size / _GLYPH_GRID)
    draw(painter, colour)
    painter.end()
    return QIcon(pixmap)


class DashboardTools(QWidget):
    """The vertical icon strip: Title, Text Box, Shape, Arrange."""

    def __init__(self, page: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoDashboardTools")  # styled in theme.stylesheet_for

        self.title_button = self._button(
            "Add title", _draw_title, lambda: page.add_text_item(is_title=True)
        )
        self.text_button = self._button(
            "Add text box", _draw_text_box, lambda: page.add_text_item(is_title=False)
        )
        self.shape_button = self._button("Add shape", _draw_shape)
        self.arrange_button = self._button("Arrange", _draw_arrange)

        self._shape_menu = fill_shape_menu(QMenu(self), page)
        self.shape_button.setMenu(self._shape_menu)
        self.shape_button.setPopupMode(QToolButton.InstantPopup)

        self._arrange_menu = fill_arrange_menu(QMenu(self), page)
        self.arrange_button.setMenu(self._arrange_menu)
        self.arrange_button.setPopupMode(QToolButton.InstantPopup)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 8, 5, 8)
        layout.setSpacing(4)
        for button in self.buttons():
            layout.addWidget(button)
        layout.addStretch(1)

        self.setFixedWidth(BUTTON_SIZE + 10)
        self.apply_theme()
        self.set_has_selection(False)

    # -- internals ----------------------------------------------------

    def _button(
        self,
        tooltip: str,
        draw: Callable[[QPainter, QColor], None],
        on_click: Callable[[], Any] | None = None,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("ruysoDashTool")
        button.setToolTip(tooltip)
        button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setAutoRaise(True)
        button._ruyso_glyph = draw  # repainted on a theme change
        if on_click is not None:
            button.clicked.connect(lambda _checked=False: on_click())
        return button

    def buttons(self) -> list[QToolButton]:
        return [
            self.title_button,
            self.text_button,
            self.shape_button,
            self.arrange_button,
        ]

    # -- state --------------------------------------------------------

    def set_has_selection(self, has_selection: bool) -> None:
        """Enable Arrange only while there is something to arrange."""
        self.arrange_button.setEnabled(has_selection)
        self.arrange_button.setToolTip(
            "Arrange" if has_selection else _ARRANGE_EMPTY_HINT
        )

    def apply_theme(self) -> None:
        """Repaint every glyph in the active theme's text colour."""
        colour = QColor(theme.current_theme().text_color)
        colour.setAlpha(205)  # a shade quieter than body text
        for button in self.buttons():
            button.setIcon(make_icon(button._ruyso_glyph, colour))
