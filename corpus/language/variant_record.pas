{ P0 fixture — language: variant records (old-style case fields), binary layout risk.
  Expected: compiles with FPC; layout must be preserved by any future IR. }
program VariantRecord;
type
  TTagged = record
    Kind: (kInt, kStr);
    case Integer of
      0: (IntValue: LongInt);
      1: (StrValue: string[31]);
  end;
var
  V: TTagged;
begin
  V.Kind := kInt;
  V.IntValue := 123456;
  writeln('variant int=', V.IntValue);
  V.Kind := kStr;
  V.StrValue := 'abc';
  writeln('variant str=', V.StrValue)
end.
