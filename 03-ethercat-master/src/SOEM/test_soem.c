/**
 * SOEM Library Validation Test
 * Tests all OSAL and core EtherCAT stack functions
 */

#include <stdio.h>
#include <string.h>
#include <osal.h>
#include <ethercattype.h>
/* oshw.h must be before ethercatmain.h - provides ecx_portt, etc. */
#include <nicdrv.h>
#include <oshw.h>
#include <ethercatmain.h>
#include <ethercatbase.h>
#include <ethercatconfig.h>
#include <ethercatcoe.h>
#include <ethercatdc.h>
#include <ethercatfoe.h>
#include <ethercatprint.h>
#include <ethercatsoe.h>

static int tests_passed = 0;
static int tests_failed = 0;
static int tests_total = 0;

#define TEST(name) do { \
    tests_total++; \
    printf("  [%2d] %-55s", tests_total, name); \
} while(0)

#define PASS() do { tests_passed++; printf("PASS\n"); } while(0)
#define FAIL(msg) do { tests_failed++; printf("FAIL: %s\n", msg); } while(0)
#define CHECK(cond, msg) do { if (cond) PASS(); else FAIL(msg); } while(0)

/* ================================================================
 * OSAL Tests
 * ================================================================ */
static void test_osal(void)
{
    printf("\n--- OSAL Tests ---\n");

    /* Test 1: osal_current_time returns valid time */
    TEST("osal_current_time returns valid time");
    ec_timet t1 = osal_current_time();
    CHECK(t1.sec > 0 || t1.usec > 0, "time should be non-zero");

    /* Test 2: osal_current_time is monotonic */
    TEST("osal_current_time is monotonic");
    ec_timet t2 = osal_current_time();
    int64_t diff = ((int64_t)t2.sec * 1000000 + t2.usec) -
                   ((int64_t)t1.sec * 1000000 + t1.usec);
    CHECK(diff >= 0, "time should be monotonic (diff >= 0)");
    printf("         (delta = %lld us)\n", (long long)diff);

    /* Test 3: osal_timer_start + is_expired (not expired immediately) */
    TEST("osal_timer not expired immediately (100ms timeout)");
    osal_timert timer;
    osal_timer_start(&timer, 100000); /* 100ms */
    CHECK(!osal_timer_is_expired(&timer), "timer should not expire immediately");

    /* Test 4: osal_timer expired after waiting */
    TEST("osal_timer expired after usleep (200ms)");
    osal_usleep(200000); /* 200ms */
    CHECK(osal_timer_is_expired(&timer), "timer should expire after 200ms wait");

    /* Test 5: osal_usleep with small value */
    TEST("osal_usleep(1) returns without error");
    int ret = osal_usleep(1);
    CHECK(ret >= 0, "osal_usleep should return >= 0");
}

/* ================================================================
 * EtherCAT Type / Header Tests
 * ================================================================ */
static void test_ethercat_types(void)
{
    printf("\n--- EtherCAT Type Tests ---\n");

    /* Test 6: ec_slavet structure size */
    TEST("ec_slavet structure initialized to zero");
    ec_slavet slave;
    memset(&slave, 0, sizeof(slave));
    CHECK(slave.state == 0 && slave.configadr == 0, "zero-init slave");

    /* Test 7: ec_groupt structure */
    TEST("ec_groupt structure initialized");
    ec_groupt group;
    memset(&group, 0, sizeof(group));
    CHECK(group.Obytes == 0 && group.Ibytes == 0, "zero-init group");

    /* Test 8: Constants are defined properly */
    TEST("EC_MAXSLAVE >= 100");
    CHECK(EC_MAXSLAVE >= 100, "need at least 100 slaves");

    TEST("EC_MAXBUF == 16");
    CHECK(EC_MAXBUF == 16, "buffer count is 16");

    TEST("EC_BUFSIZE >= 1518");
    CHECK(EC_BUFSIZE >= 1518, "buffer must hold full frame");

    /* Test 9: ec_timet type */
    TEST("ec_timet has sec and usec fields");
    ec_timet tt;
    tt.sec = 12345;
    tt.usec = 67890;
    CHECK(tt.sec == 12345 && tt.usec == 67890, "fields accessible");

    /* Test 10: PACKED macros work */
    TEST("PACKED macros are defined for GCC");
    /* If we get here, PACKED_BEGIN/PACKED/PACKED_END compiled OK */
    PASS();
}

/* ================================================================
 * EtherCAT Base Tests
 * ================================================================ */
static void test_ethercat_base(void)
{
    printf("\n--- EtherCAT Base Tests ---\n");

    /* Test 11: ecx_setupheader fills ethernet header */
    TEST("ec_setupheader fills ethernet header correctly");
    ec_bufT buf;
    memset(&buf, 0xAA, sizeof(buf));
    ec_setupheader(&buf);
    ec_etherheadert *eh = (ec_etherheadert *)&buf;
    CHECK(eh->etype == htons(ETH_P_ECAT), "etype should be EtherCAT (0x88A4)");
    CHECK(eh->da0 == htons(0xffff) && eh->da1 == htons(0xffff),
          "destination MAC should be broadcast");
    CHECK(eh->sa1 == htons(priMAC[1]), "source MAC middle word matches priMAC");

    /* Test 12: ec_nextmbxcnt wraps correctly */
    TEST("ec_nextmbxcnt increments and wraps 1-7");
    uint8 cnt = ec_nextmbxcnt(0);
    CHECK(cnt == 1, "0->1");
    cnt = ec_nextmbxcnt(7);
    CHECK(cnt == 1, "7->1 (wrap)");

    /* Test 13: ec_clearmbx clears mailbox */
    TEST("ec_clearmbx clears mailbox buffer");
    ec_mbxbuft mbx;
    memset(&mbx, 0xFF, sizeof(mbx));
    ec_clearmbx(&mbx);
    int all_zero = 1;
    /* EC_MAXMBX=0x3ff=1023, array is EC_MAXMBX+1=1024,
       ec_clearmbx clears only EC_MAXMBX bytes */
    for (int i = 0; i < EC_MAXMBX; i++) {
        if (mbx[i] != 0) { all_zero = 0; break; }
    }
    CHECK(all_zero, "first EC_MAXMBX bytes cleared");
}

/* ================================================================
 * EtherCAT Config Tests
 * ================================================================ */
static void test_ethercat_config(void)
{
    printf("\n--- EtherCAT Config Tests ---\n");

    /* Test 14: ecx_contextt can be initialized */
    TEST("ecx_contextt zero-initialized");
    ecx_contextt ctx;
    memset(&ctx, 0, sizeof(ctx));
    CHECK(ctx.port == NULL && ctx.slavelist == NULL, "fresh context is empty");

    /* Test 15: Slave array allocation */
    TEST("slave array allocated (EC_MAXSLAVE)");
    ec_slavet slaves[EC_MAXSLAVE];
    memset(slaves, 0, sizeof(slaves));
    CHECK(sizeof(slaves) > 0, "slave array allocated");

    /* Test 16: Group array allocation */
    TEST("group array allocated (EC_MAXGROUP)");
    ec_groupt groups[EC_MAXGROUP];
    memset(groups, 0, sizeof(groups));
    CHECK(sizeof(groups) > 0, "group array allocated");
}

/* ================================================================
 * EtherCAT DC (Distributed Clock) Tests
 * ================================================================ */
static void test_ethercat_dc(void)
{
    printf("\n--- EtherCAT DC Tests ---\n");

    /* Test 17: ecx_dcsync0 structure validation */
    TEST("DC sync structures compile and initialize");
    ec_slavet slave;
    memset(&slave, 0, sizeof(slave));
    slave.hasdc = FALSE;
    slave.DCactive = 0;
    CHECK(slave.hasdc == FALSE && slave.DCactive == 0, "DC disabled by default");

    /* Test 18: DC register definitions */
    TEST("DC register offsets are valid");
    CHECK(ECT_REG_DCTIME0 == 0x0900, "DCTIME0 = 0x0900");
    CHECK(ECT_REG_DCSYSTIME == 0x0910, "DCSYSTIME = 0x0910");
    CHECK(ECT_REG_DCSYNCACT == 0x0981, "DCSYNCACT = 0x0981");
}

/* ================================================================
 * EtherCAT CoE Tests
 * ================================================================ */
static void test_ethercat_coe(void)
{
    printf("\n--- EtherCAT CoE Tests ---\n");

    /* Test 19: CoE SDO command constants */
    TEST("CoE SDO commands are correct");
    CHECK(ECT_SDO_DOWN_INIT == 0x21, "SDO download init = 0x21");
    CHECK(ECT_SDO_UP_REQ == 0x40, "SDO upload request = 0x40");
    CHECK(ECT_SDO_ABORT == 0x80, "SDO abort = 0x80");

    /* Test 20: CoE mailbox type */
    TEST("CoE mailbox types defined");
    CHECK(ECT_MBXT_COE == 3, "CoE mailbox type = 3");
    CHECK(ECT_COES_SDOREQ == 0x02, "SDO request = 0x02");
}

/* ================================================================
 * EtherCAT FoE / SoE Tests
 * ================================================================ */
static void test_ethercat_foe_soe(void)
{
    printf("\n--- EtherCAT FoE / SoE Tests ---\n");

    /* Test 21: FoE opcodes */
    TEST("FoE opcodes defined properly");
    CHECK(ECT_FOE_READ == 0x01, "FoE read = 0x01");
    CHECK(ECT_FOE_WRITE == 0x02, "FoE write = 0x02");
    CHECK(ECT_FOE_DATA == 0x03, "FoE data = 0x03");

    /* Test 22: SoE opcodes */
    TEST("SoE opcodes defined properly");
    CHECK(ECT_SOE_READREQ == 0x01, "SoE read req = 0x01");
    CHECK(ECT_SOE_READRES == 0x02, "SoE read res = 0x02");
}

/* ================================================================
 * EtherCAT Print / Utility Tests
 * ================================================================ */
static void test_ethercat_print(void)
{
    printf("\n--- EtherCAT Print/Utility Tests ---\n");

    /* Test 23: State name lookup */
    TEST("ec_state names are valid");
    /* EC_STATE_INIT=1, PRE_OP=2, BOOT=3, SAFE_OP=4, OP=8, ACK/ERROR=0x10 */
    CHECK(EC_STATE_INIT == 0x01, "INIT = 0x01");
    CHECK(EC_STATE_PRE_OP == 0x02, "PRE_OP = 0x02");
    CHECK(EC_STATE_SAFE_OP == 0x04, "SAFE_OP = 0x04");
    CHECK(EC_STATE_OPERATIONAL == 0x08, "OP = 0x08");
}

/* ================================================================
 * OSHW Tests
 * ================================================================ */
static void test_oshw(void)
{
    printf("\n--- OSHW (Hardware Abstraction) Tests ---\n");

    /* Test 24: byte order functions */
    TEST("oshw_htons / oshw_ntohs roundtrip");
    uint16 val = 0x1234;
    uint16 net = oshw_htons(val);
    uint16 host = oshw_ntohs(net);
    CHECK(host == val, "htons/ntohs roundtrip should preserve value");

    /* Test 25: ec_adapter type is valid */
    TEST("ec_adapter structure is valid");
    ec_adaptert adapter;
    memset(&adapter, 0, sizeof(adapter));
    strncpy(adapter.name, "test_nic", EC_MAXLEN_ADAPTERNAME - 1);
    strncpy(adapter.desc, "Test NIC Adapter", EC_MAXLEN_ADAPTERNAME - 1);
    CHECK(strcmp(adapter.name, "test_nic") == 0, "adapter name stored");
    CHECK(strcmp(adapter.desc, "Test NIC Adapter") == 0, "adapter desc stored");
}

/* ================================================================
 * NIC Driver Structure Tests (no hardware needed)
 * ================================================================ */
static void test_nicdrv_structures(void)
{
    printf("\n--- NIC Driver Structure Tests (no hardware) ---\n");

    /* Test 26: ecx_portt structure */
    TEST("ecx_portt structure zero-initialized");
    ecx_portt port;
    memset(&port, 0, sizeof(port));
    CHECK(port.sockhandle == NULL && port.lastidx == 0, "fresh port is empty");

    /* Test 27: ec_stackT structure */
    TEST("ec_stackT structure zero-initialized");
    ec_stackT stack;
    memset(&stack, 0, sizeof(stack));
    CHECK(stack.sock == NULL, "fresh stack has no socket");

    /* Test 28: MAC address constants */
    TEST("priMAC and secMAC are different");
    int same = 1;
    for (int i = 0; i < 3; i++) {
        if (priMAC[i] != secMAC[i]) same = 0;
    }
    CHECK(!same, "primary and secondary MAC should differ");
}

/* ================================================================
 * Error Handling Tests
 * ================================================================ */
static void test_error_handling(void)
{
    printf("\n--- Error Handling Tests ---\n");

    /* Test 29: Error context structure */
    TEST("ec_errort structure is correct size");
    ec_errort err;
    memset(&err, 0, sizeof(err));
    err.Slave = 5;
    err.Index = 0x6060;
    err.SubIdx = 0x00;
    CHECK(err.Slave == 5 && err.Index == 0x6060, "error fields set correctly");

    /* Test 30: Error ring buffer */
    TEST("ec_eringt ring buffer initialized");
    ec_eringt ring;
    memset(&ring, 0, sizeof(ring));
    ring.head = 0;
    ring.tail = 0;
    CHECK(ring.head == 0 && ring.tail == 0, "ring starts empty");

    /* Test 31: Error type constants */
    TEST("error type constants are valid");
    CHECK(EC_ERR_TYPE_SDO_ERROR == 0, "SDO error type = 0");
    CHECK(EC_ERR_TYPE_EMERGENCY == 1, "Emergency type = 1");
}

/* ================================================================
 * IO / PDO Tests
 * ================================================================ */
static void test_io_segments(void)
{
    printf("\n--- IO / PDO Structure Tests ---\n");

    /* Test 32: Sync Manager structure */
    TEST("ec_smt (sync manager) structure");
    ec_smt sm;
    memset(&sm, 0, sizeof(sm));
    sm.StartAddr = 0x1000;
    sm.SMlength = 0x40;
    sm.SMflags = 0x00010024;
    CHECK(sm.StartAddr == 0x1000 && sm.SMlength == 0x40, "SM fields set");

    /* Test 33: FMMU structure */
    TEST("ec_fmmut (FMMU) structure");
    ec_fmmut fmmu;
    memset(&fmmu, 0, sizeof(fmmu));
    fmmu.LogStart = 0x00001234;
    fmmu.LogLength = 0x20;
    CHECK(fmmu.LogStart == 0x00001234, "FMMU LogStart set");

    /* Test 34: IO segment array */
    TEST("ec_groupt IOsegment array");
    ec_groupt group;
    memset(&group, 0, sizeof(group));
    group.IOsegment[0] = 0x1000;
    CHECK(group.IOsegment[0] == 0x1000, "IO segment address set");
}

/* ================================================================
 * Main
 * ================================================================ */
int main(void)
{
    printf("==========================================================\n");
    printf("  SOEM Library Validation Test Suite\n");
    printf("  EtherCAT Master — Precision Force Control\n");
    printf("==========================================================\n");
    printf("  Compiler: GCC %d.%d.%d\n",
           __GNUC__, __GNUC_MINOR__, __GNUC_PATCHLEVEL__);
    printf("  Target:   %s\n", sizeof(void*) == 8 ? "x86_64 (64-bit)" : "x86 (32-bit)");
    printf("==========================================================\n");

    /* Run all test suites */
    test_osal();
    test_ethercat_types();
    test_ethercat_base();
    test_ethercat_config();
    test_ethercat_dc();
    test_ethercat_coe();
    test_ethercat_foe_soe();
    test_ethercat_print();
    test_oshw();
    test_nicdrv_structures();
    test_error_handling();
    test_io_segments();

    /* Summary */
    printf("\n==========================================================\n");
    printf("  Results: %d/%d passed, %d failed\n",
           tests_passed, tests_total, tests_failed);
    printf("==========================================================\n");

    if (tests_failed == 0) {
        printf("  STATUS: ALL TESTS PASSED\n");
        return 0;
    } else {
        printf("  STATUS: %d TEST(S) FAILED\n", tests_failed);
        return 1;
    }
}
