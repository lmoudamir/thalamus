WITH RECURSIVE
  fib(n, a, b) AS (
    SELECT 1, 0, 1
    UNION ALL
    SELECT n+1, b, a+b FROM fib WHERE n < 20
  ),
  collatz(step, val) AS (
    SELECT 0, 27
    UNION ALL
    SELECT step+1,
      CASE WHEN val % 2 = 0 THEN val / 2
           ELSE val * 3 + 1
      END
    FROM collatz WHERE val > 1
  ),
  pascal(row, seq) AS (
    SELECT 0, '1'
    UNION ALL
    SELECT row+1,
      (SELECT GROUP_CONCAT(
        COALESCE(
          CAST(
            CAST(SUBSTR(p.token, 1, INSTR(p.token||',',',')-1) AS INT) +
            CAST(SUBSTR(p.token, INSTR(p.token||',',' ')+1) AS INT)
          AS TEXT),
          '1'
        ), ','
       ) FROM (SELECT seq AS token FROM pascal WHERE row = pascal.row) p)
    FROM pascal WHERE row < 8
  )
SELECT 'fibonacci' AS series, n, b AS value FROM fib
UNION ALL
SELECT 'collatz_27', step, val FROM collatz
UNION ALL
SELECT 'pascal_row', row, seq FROM pascal;
