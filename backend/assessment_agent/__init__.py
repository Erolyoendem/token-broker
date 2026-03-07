"""
Assessment Agent – automatisierte Big-4-Statusanalyse fuer Codebases.

Komponenten:
  code_scanner        – Projektstruktur, LOC, Frameworks
  dependency_analyzer – Abhaengigkeitsgraph + Pain-Points
  tech_debt_estimator – Tech-Debt-Score (0-100)
  report_generator    – LLM-gestuetzter Bericht im Big-4-Stil
"""
from .code_scanner import CodeScanner, ScanResult
from .dependency_analyzer import AssessmentDependencyAnalyzer, PainPoint
from .tech_debt_estimator import TechDebtEstimator, TechDebtResult
from .report_generator import ReportGenerator

__all__ = [
    "CodeScanner", "ScanResult",
    "AssessmentDependencyAnalyzer", "PainPoint",
    "TechDebtEstimator", "TechDebtResult",
    "ReportGenerator",
]
