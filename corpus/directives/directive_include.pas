{ P0 fixture — directives: $INCLUDE / $I pulling a shared include file.
  Expected: compiles with FPC when resolved from the same directory. }
program DirectiveInclude;
{$I include_shared.inc}
begin
  writeln('include magic=', MAGIC_VALUE)
end.
