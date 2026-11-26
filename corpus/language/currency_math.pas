{ P0 fixture — language: Currency (fixed-point money) and rounding behavior.
  Expected: compiles with FPC; rounding results are a differential-test oracle target. }
program CurrencyMath;
var
  Price: Currency;
  Tax: Currency;
  Total: Currency;
begin
  Price := 19.99;
  Tax := Price * 0.0725;
  Total := Price + Tax;
  writeln('price=', Price:0:2, ' tax=', Tax:0:2, ' total=', Total:0:2);
  writeln('rounded=', Round(Total * 100) / 100:0:2)
end.
