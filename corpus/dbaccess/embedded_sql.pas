{ P0 fixture — database access: embedded SQL statements as string literals.
  No DB framework present; SQL text must be extracted by discovery, not executed.
  Expected: compiles with FPC (SQL is inert string data here). }
program EmbeddedSql;
{$mode objfpc}
const
  SQL_SELECT =
    'SELECT c.id, c.name, o.total ' +
    'FROM customers c JOIN orders o ON o.customer_id = c.id ' +
    'WHERE o.created_at >= :since AND c.region IN (:region) ' +
    'ORDER BY o.total DESC';
  SQL_UPDATE =
    'UPDATE accounts SET balance = balance + :delta WHERE account_no = :acct';
  SQL_PROC_CALL = 'EXEC monthly_reconcile :year, :month';
begin
  writeln('sql select len=', Length(SQL_SELECT));
  writeln('sql update len=', Length(SQL_UPDATE));
  writeln('sql proc len=', Length(SQL_PROC_CALL))
end.
