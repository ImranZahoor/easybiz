from easybiz.core.kernel import extensions


def all_greetings() -> list[str]:
    """Collect a greeting from every enabled contributor to the demo.greeters point."""
    return [g.greet() for g in extensions.contributors("demo.greeters")]
