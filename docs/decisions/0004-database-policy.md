# ADR 0004: Database policy — preserve-first

- **Status:** Accepted
- **Date:** 2026-11-13
- **Phase:** P0 (policy decision; first DB adapter lands in P4)
- **Source of truth:** master prompt *Database policy*; architecture v3.0
  dependency-domain table

## Context

Legacy Pascal estates are usually coupled to an existing database with
procedures, views, triggers and contracts that took years to accumulate.
Rewriting the database while rewriting the language doubles the risk and
destroys the one asset that is already certified by production use.

Two further constraints shape the decision:

- The platform's own **metadata store** is a different thing from a
  **customer's target database**, and conflating them would force customers onto
  a DBMS they did not choose.
- Discovery must **recognise** many DBMSs without pretending to **support** them
  all. The architecture states this directly: *"Inventory list is not a support
  promise."*

## Decision

**Mode A — Preserve the existing database. This is the default and the only
mode P0–P5 implement.**

1. Connect to the **same customer DBMS and schema** using JDBC/vendor drivers.
   Stored procedures, views and contracts are preserved, not translated.
2. **Read-only discovery** via `java.sql.DatabaseMetaData` for tables, columns,
   keys and procedures, wherever the driver provides them. No writes during
   discovery.
3. **Explicit SQL** through JDBC or MyBatis where appropriate. **No forced ORM
   translation** — an ORM would silently change null, rounding and locking
   behaviour, which is exactly what differential certification exists to detect.
4. **Test on cloned snapshots:** transactions, isolation, autocommit, locking,
   triggers, rounding, NULL and error behaviour.
5. **No hidden schema rewrite, no data move.**

**Mode B — Optional database migration. Out of scope until a customer asks.**

6. Requires **explicit customer approval** and a **separate workstream**.
7. Must produce source/target schema map, conversion rules, migration plan,
   rollback, restore tests, reconciliation and transaction-parity evidence.
8. **A successful source conversion never implies database migration is
   complete.** The two verdicts are reported separately and never merged.

**Platform metadata store**

9. **PostgreSQL 18.7** holds *platform metadata only* — manifests, graphs,
   evidence, certification records. It is **not** a forced customer target DB
   and must never appear as one in generated output.

**Discovery scope**

10. Discovery recognises Oracle, IBM DB2, SQL Server, PostgreSQL,
    MySQL/MariaDB, Firebird, InterBase, Informix, Sybase, SQLite, Access,
    Paradox, dBASE and FoxPro — as **inventory**, each carrying
    `DBMS/version/driver, tables/views, keys, constraints, sequences, triggers,
    procedures, data types and isolation`. Recognition ≠ support.

## Consequences

- **Lower risk per conversion:** only the language layer changes, so a failed
  conversion has a much smaller blast radius.
- **The database becomes a stable differential target:** the same schema is
  used by both lanes, so P6 comparisons isolate *program* behaviour rather than
  *schema* differences.
- **Support is earned fixture-by-fixture.** A DBMS appears in the inventory
  long before it appears in any `SUPPORTED` claim; each needs its own fixtures
  and certification evidence (P8 rule).
- **P0 evidence that seeds this policy:**
  - `dbaccess/embedded_sql.pas` — SQL exists as **inert string literals** that
    must be *extracted* by discovery, never executed during analysis. Its run
    output (`sql select len=160`, etc.) confirms the fixture is data, not a live
    query.
  - `dbaccess/ado_style_connection.pas` — data access through **native/COM**
    dependencies (`ComObj`) that are platform-dependent: PASS on Windows,
    `Can't find unit ComObj` on Linux. Recorded as compile-only because no
    provider is registered, so the runtime path is deliberately not exercised.
  - `dbaccess/bde_style_query.pas` — BDE is a declared `FAIL-DEPENDENCY`
    (unit absent), proving legacy data-access stacks must be *discovered as
    dependencies*, not assumed present.
- **Mode B must stay visibly separate** in reporting; merging its verdict into
  the conversion verdict would be a false-completion risk.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| ORM-first generated data access (JPA/Hibernate) | Would translate null/rounding/locking semantics implicitly, breaking differential equivalence and hiding exactly the behaviours under test. |
| Always migrate to PostgreSQL | Forces a DBMS change on customers who only wanted the code converted; contradicts "preserve-first" and turns every job into two projects. |
| Migrate opportunistically during conversion | A source conversion succeeding must never imply migration completeness — merging the two is a false-completion hazard. |
| Read-write discovery for richer metadata | Unacceptable risk on production schemas; read-only is sufficient for everything P2 needs. |
| SQL AST parsing of all vendor SQL (JSqlParser) | Out of scope and explicitly licensed-conditionally; P0 treats SQL as inert strings. Revisit only for tested syntax, after licence review. |

## Revisit triggers

- A customer explicitly requests Mode B (then: new ADR, separate workstream).
- A target DBMS gains its own fixtures and certification evidence (then: it may
  move from *inventory* to *supported*, one DBMS at a time).
- Licence review clears SchemaCrawler or JSqlParser for a specific route
  (recorded as deferred, not assumed).
