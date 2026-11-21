"""Shared helpers for the test_code_structure_snapshot_* modules."""


_JAVA_DOCUMENT = """package com.acme.core;

public abstract class Document {
    private UUID id;
    private Instant createdAt;

    public UUID getId() { return id; }
}
"""


_JAVA_INVOICE = """package com.acme.billing;

import com.acme.core.Document;
import com.acme.core.AuditLog;

public class Invoice extends Document implements Payable {
    private BigDecimal total;
    private List<LineItem> items;

    public Invoice(UUID id) {}

    public BigDecimal computeTotal(TaxPolicy policy) { return total; }

    public void addItem(LineItem item) {}
}
"""


_JAVA_AUDIT_LOG = """package com.acme.core;

public class AuditLog {
    private String entry;
}
"""


_PYTHON_MODEL = '''from dataclasses import dataclass


class InvoiceModel(BaseModel):
    amount: float = 0.0
    currency = "EUR"

    def to_dict(self, include_none: bool = False):
        return {}
'''


def _fixture_workspace(tmp_path):
    core = tmp_path / "src" / "com" / "acme" / "core"
    billing = tmp_path / "src" / "com" / "acme" / "billing"
    core.mkdir(parents=True)
    billing.mkdir(parents=True)
    (core / "Document.java").write_text(_JAVA_DOCUMENT)
    (core / "AuditLog.java").write_text(_JAVA_AUDIT_LOG)
    (billing / "Invoice.java").write_text(_JAVA_INVOICE)
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "models.py").write_text(_PYTHON_MODEL)
    return tmp_path
