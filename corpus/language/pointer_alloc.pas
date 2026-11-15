{ P0 fixture — language: manual pointer allocation and typed pointers.
  Expected: compiles with FPC; memory-ownership semantics require a compatibility adapter. }
program PointerAlloc;
type
  PNode = ^TNode;
  TNode = record
    Value: Integer;
    Next: PNode;
  end;
var
  Head, Current: PNode;
  I: Integer;
begin
  New(Head);
  Head^.Value := 1;
  Head^.Next := nil;
  Current := Head;
  for I := 2 to 4 do
  begin
    New(Current^.Next);
    Current := Current^.Next;
    Current^.Value := I;
    Current^.Next := nil;
  end;
  Current := Head;
  while Current <> nil do
  begin
    write(Current^.Value, ' ');
    Current := Current^.Next;
  end;
  writeln;
  Current := Head;
  while Current <> nil do
  begin
    Head := Current^.Next;
    Dispose(Current);
    Current := Head;
  end;
  writeln('pointer-list-done')
end.
