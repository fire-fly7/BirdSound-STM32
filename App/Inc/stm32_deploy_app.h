#ifndef STM32_DEPLOY_APP_H
#define STM32_DEPLOY_APP_H

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Initialize and run the application selected by STM32_DEPLOY_APP.
 *
 * The active application owns its board-facing peripherals. A non-zero return
 * value means application initialization failed; successful applications are
 * expected to keep control of the main loop.
 */
int STM32DeployApp_Run(void);

#ifdef __cplusplus
}
#endif

#endif /* STM32_DEPLOY_APP_H */
