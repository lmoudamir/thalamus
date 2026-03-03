#include <stdio.h>
#define P(x) ((x)>1&&P##2(x,2))
#define P2(x,d) ((d)*(d)>(x)?1:(x)%(d)?P##2(x,(d)+1):0)
#define S(a,b) ((a)>(b)?(a):(b))
#define ABS(x) ((x)<0?-(x):(x))

typedef struct { double r; double i; } cplx;

cplx cmul(cplx a, cplx b) {
    return (cplx){a.r*b.r - a.i*b.i, a.r*b.i + a.i*b.r};
}
cplx cadd(cplx a, cplx b) { return (cplx){a.r+b.r, a.i+b.i}; }
double cmag2(cplx c) { return c.r*c.r + c.i*c.i; }

int mandelbrot(double cr, double ci, int max) {
    cplx z = {0, 0}, c = {cr, ci};
    for (int i = 0; i < max; i++) {
        z = cadd(cmul(z, z), c);
        if (cmag2(z) > 4.0) return i;
    }
    return max;
}

int main() {
    const int W = 78, H = 30, ITER = 100;
    const char *shade = " .:-=+*#%@";
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            double cr = (x - W * 0.7) / (W * 0.35);
            double ci = (y - H / 2.0) / (H * 0.45);
            int n = mandelbrot(cr, ci, ITER);
            putchar(shade[n < ITER ? (n * 9 / ITER) : 0]);
        }
        putchar('\n');
    }
    return 0;
}
