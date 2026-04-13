"""Focused tests for CLI aliases and lightweight command routing."""

from gengowatcher.cli import build_argument_parser, should_handle_lightweight_command


def test_configure_alias_maps_to_configure_flag():
    parser = build_argument_parser()

    args = parser.parse_args(["--config"])

    assert args.configure is True
    assert should_handle_lightweight_command(args) is True


def test_setup_aliases_map_to_email_and_website_flags():
    parser = build_argument_parser()

    email_args = parser.parse_args(["--setup-mail"])
    website_args = parser.parse_args(["--setup-web"])
    website_site_args = parser.parse_args(["--setup-site"])

    assert email_args.setup_email is True
    assert website_args.setup_website is True
    assert website_site_args.setup_website is True
