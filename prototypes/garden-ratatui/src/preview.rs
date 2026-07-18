//! Deterministic SVG previews rendered from Ratatui's `TestBackend`.

use std::{
    fmt::Write as _,
    fs, io,
    path::{Path, PathBuf},
};

use ratatui::{
    Terminal,
    backend::TestBackend,
    buffer::{Buffer, Cell},
    style::{Color, Modifier},
};

use crate::{
    App, View, render,
    theme::{SVG_BACKGROUND, SVG_FOREGROUND},
};

const COLUMNS: u16 = 150;
const ROWS: u16 = 44;
const CELL_WIDTH: u32 = 10;
const CELL_HEIGHT: u32 = 20;

/// Render all workspaces at the same 150 × 44 terminal size as the Textual
/// reference images.
pub fn render_previews(output_dir: &Path) -> io::Result<Vec<PathBuf>> {
    fs::create_dir_all(output_dir)?;
    let mut paths = Vec::with_capacity(View::ALL.len());
    for view in View::ALL {
        let backend = TestBackend::new(COLUMNS, ROWS);
        let mut terminal = Terminal::new(backend).expect("TestBackend is infallible");
        let mut app = App::new(view);
        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("TestBackend is infallible");
        let svg = buffer_to_svg(terminal.backend().buffer());
        let path = output_dir.join(format!("garden-ratatui-{}.svg", view.slug()));
        fs::write(&path, svg)?;
        paths.push(path);
    }
    Ok(paths)
}

fn buffer_to_svg(buffer: &Buffer) -> String {
    let width = u32::from(buffer.area().width) * CELL_WIDTH;
    let height = u32::from(buffer.area().height) * CELL_HEIGHT;
    let mut svg = String::with_capacity(buffer.content().len() * 80);
    writeln!(
        svg,
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"GengoWatcher Ratatui terminal preview\">"
    )
    .expect("writing to String cannot fail");
    writeln!(
        svg,
        "<rect width=\"100%\" height=\"100%\" fill=\"{SVG_BACKGROUND}\"/>"
    )
    .expect("writing to String cannot fail");
    svg.push_str("<g shape-rendering=\"crispEdges\">\n");
    render_backgrounds(buffer, &mut svg);
    svg.push_str("</g>\n<g font-family=\"'DejaVu Sans Mono','Liberation Mono',monospace\" font-size=\"15\">\n");
    render_symbols(buffer, &mut svg);
    svg.push_str("</g>\n</svg>\n");
    svg
}

fn render_backgrounds(buffer: &Buffer, svg: &mut String) {
    let width = buffer.area().width;
    for y in 0..buffer.area().height {
        let mut x = 0;
        while x < width {
            let cell = cell_at(buffer, x, y);
            let color = color_hex(cell.bg, SVG_BACKGROUND);
            let mut run = 1;
            while x + run < width
                && color_hex(cell_at(buffer, x + run, y).bg, SVG_BACKGROUND) == color
            {
                run += 1;
            }
            if color != SVG_BACKGROUND {
                let pixel_x = u32::from(x) * CELL_WIDTH;
                let pixel_y = u32::from(y) * CELL_HEIGHT;
                let pixel_width = u32::from(run) * CELL_WIDTH;
                writeln!(svg, "<rect x=\"{pixel_x}\" y=\"{pixel_y}\" width=\"{pixel_width}\" height=\"{CELL_HEIGHT}\" fill=\"{color}\"/>").expect("writing to String cannot fail");
            }
            x += run;
        }
    }
}

fn render_symbols(buffer: &Buffer, svg: &mut String) {
    for y in 0..buffer.area().height {
        for x in 0..buffer.area().width {
            let cell = cell_at(buffer, x, y);
            let symbol = cell.symbol();
            if symbol.trim().is_empty() || cell.modifier.contains(Modifier::HIDDEN) {
                continue;
            }
            let pixel_x = u32::from(x) * CELL_WIDTH;
            let baseline = u32::from(y) * CELL_HEIGHT + 15;
            let fill = color_hex(cell.fg, SVG_FOREGROUND);
            let weight = if cell.modifier.contains(Modifier::BOLD) {
                " font-weight=\"700\""
            } else {
                ""
            };
            let italic = if cell.modifier.contains(Modifier::ITALIC) {
                " font-style=\"italic\""
            } else {
                ""
            };
            let decoration = if cell
                .modifier
                .intersects(Modifier::UNDERLINED | Modifier::CROSSED_OUT)
            {
                let value = match (
                    cell.modifier.contains(Modifier::UNDERLINED),
                    cell.modifier.contains(Modifier::CROSSED_OUT),
                ) {
                    (true, true) => "underline line-through",
                    (true, false) => "underline",
                    (false, true) => "line-through",
                    (false, false) => unreachable!(),
                };
                format!(" text-decoration=\"{value}\"")
            } else {
                String::new()
            };
            let opacity = if cell.modifier.contains(Modifier::DIM) {
                " opacity=\"0.65\""
            } else {
                ""
            };
            writeln!(svg, "<text x=\"{pixel_x}\" y=\"{baseline}\" fill=\"{fill}\"{weight}{italic}{decoration}{opacity}>{}</text>", escape_xml(symbol)).expect("writing to String cannot fail");
        }
    }
}

fn cell_at(buffer: &Buffer, x: u16, y: u16) -> &Cell {
    let width = usize::from(buffer.area().width);
    &buffer.content()[usize::from(y) * width + usize::from(x)]
}

fn color_hex(color: Color, reset: &'static str) -> String {
    match color {
        Color::Reset => reset.into(),
        Color::Black => "#000000".into(),
        Color::Red => "#800000".into(),
        Color::Green => "#008000".into(),
        Color::Yellow => "#808000".into(),
        Color::Blue => "#000080".into(),
        Color::Magenta => "#800080".into(),
        Color::Cyan => "#008080".into(),
        Color::Gray => "#c0c0c0".into(),
        Color::DarkGray => "#808080".into(),
        Color::LightRed => "#ff0000".into(),
        Color::LightGreen => "#00ff00".into(),
        Color::LightYellow => "#ffff00".into(),
        Color::LightBlue => "#0000ff".into(),
        Color::LightMagenta => "#ff00ff".into(),
        Color::LightCyan => "#00ffff".into(),
        Color::White => "#ffffff".into(),
        Color::Rgb(red, green, blue) => format!("#{red:02x}{green:02x}{blue:02x}"),
        Color::Indexed(index) => indexed_color(index),
    }
}

fn indexed_color(index: u8) -> String {
    const BASIC: [&str; 16] = [
        "#000000", "#800000", "#008000", "#808000", "#000080", "#800080", "#008080", "#c0c0c0",
        "#808080", "#ff0000", "#00ff00", "#ffff00", "#0000ff", "#ff00ff", "#00ffff", "#ffffff",
    ];
    if index < 16 {
        return BASIC[usize::from(index)].into();
    }
    if index < 232 {
        let value = index - 16;
        let red = value / 36;
        let green = (value % 36) / 6;
        let blue = value % 6;
        let component = |channel: u8| if channel == 0 { 0 } else { 55 + channel * 40 };
        return format!(
            "#{:02x}{:02x}{:02x}",
            component(red),
            component(green),
            component(blue)
        );
    }
    let gray = 8 + (index - 232) * 10;
    format!("#{gray:02x}{gray:02x}{gray:02x}")
}

fn escape_xml(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for character in value.chars() {
        match character {
            '&' => escaped.push_str("&amp;"),
            '<' => escaped.push_str("&lt;"),
            '>' => escaped.push_str("&gt;"),
            '"' => escaped.push_str("&quot;"),
            '\'' => escaped.push_str("&apos;"),
            other => escaped.push(other),
        }
    }
    escaped
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xml_text_is_escaped() {
        assert_eq!(escape_xml("<&\"'>"), "&lt;&amp;&quot;&apos;&gt;");
    }

    #[test]
    fn indexed_palette_covers_basic_cube_and_gray_colors() {
        assert_eq!(indexed_color(9), "#ff0000");
        assert_eq!(indexed_color(16), "#000000");
        assert_eq!(indexed_color(231), "#ffffff");
        assert_eq!(indexed_color(255), "#eeeeee");
    }
}
