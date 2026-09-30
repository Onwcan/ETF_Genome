# Scala

No Scala sources are included in this directory. Python and Polars handle the current holdings tables and graph construction; the desktop runtime has no Scala or JVM dependency.

External transforms should produce validated artifacts rather than add a JVM process to desktop startup. See the [system architecture](../docs/ARCHITECTURE.md), [project status](../docs/PROJECT_STATUS.md), and the single [roadmap](../docs/ROADMAP.md) for ownership boundaries, implemented functionality, and future work.
