#include <stdint.h>
#include <sys/time.h>
typedef uint8_t boolean;
#define TRUE 1
#define FALSE 0
typedef struct { struct timeval start; } osal_timert;
void osal_timer_start(osal_timert *s, uint32_t to) { gettimeofday(&s->start,0); s->start.tv_usec+=to; }
boolean osal_timer_is_expired(osal_timert *s) { struct timeval n; gettimeofday(&n,0); return (n.tv_sec>s->start.tv_sec)||(n.tv_sec==s->start.tv_sec&&n.tv_usec>=s->start.tv_usec); }
int osal_usleep(uint32_t u) { return 0; }
typedef int64_t ec_timet;
ec_timet osal_current_time(void) { struct timeval t; gettimeofday(&t,0); return (ec_timet)t.tv_sec*1000000+t.tv_usec; }
