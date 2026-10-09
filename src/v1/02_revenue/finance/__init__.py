"""
Tax and billing mechanisms for the revenue service.

Everything here is a mechanism: how to apply a tax rule, number a document, build a billing
schedule or settle an invoice. Which taxes, rates, jurisdictions, sections, number formats and
deadlines apply is data (packs in `finance/packs`, copied into each organization's
`tax_config_entries`), never a constant in this package. `tests/test_no_tax_literals.py` keeps
it that way.

The package only depends on the rest of revenue through the models it reads, so it can move to
a billing service of its own later.
"""
