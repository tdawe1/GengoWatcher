//! Refined Kanagawa Dragon palette with strict role assignments.
//!
//! Roles:
//! - `GROUND` / `PAPER` / `CANOPY` / `NAV_BG`: elevation ladder (page →
//!   card → band → sidebar). Panels always sit on `PAPER`.
//! - `LINE`: unfocused borders and hairline rules everywhere.
//! - `INK`: primary text. `MUTED`: labels, metadata, hints.
//! - `SELECTION`: the single selection treatment (nav items, table rows).
//! - `LEAF`: healthy/success/go values and counts.
//! - `ORANGE` / `ORANGE_BG`: attention (alerts, warnings, pending states).
//! - `RED`: destructive actions and error states.
//! - `BLUE`: secondary info accents (chart glyphs, model names).
//! - `LAVENDER`: reserved for review-stage accents and the demo badge.

use ratatui::style::Color;

pub const INK: Color = Color::Rgb(197, 201, 197);
pub const MUTED: Color = Color::Rgb(166, 166, 156);
pub const GROUND: Color = Color::Rgb(24, 22, 22);
pub const PAPER: Color = Color::Rgb(29, 28, 25);
pub const CANOPY: Color = Color::Rgb(40, 39, 39);
pub const NAV_BG: Color = Color::Rgb(18, 18, 15);
pub const LINE: Color = Color::Rgb(57, 56, 54);
pub const LEAF: Color = Color::Rgb(135, 169, 135);
pub const ORANGE: Color = Color::Rgb(255, 160, 102);
pub const ORANGE_BG: Color = Color::Rgb(53, 39, 31);
pub const RED: Color = Color::Rgb(228, 104, 118);
pub const BLUE: Color = Color::Rgb(139, 164, 176);
pub const LAVENDER: Color = Color::Rgb(175, 162, 216);
pub const SELECTION: Color = Color::Rgb(45, 79, 103);

pub const SVG_BACKGROUND: &str = "#181616";
pub const SVG_FOREGROUND: &str = "#c5c9c5";
