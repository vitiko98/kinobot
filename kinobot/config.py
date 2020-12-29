#if datetime.now().strftime("%M") not in PUBLISH_MINUTES:
#    # /scripts/backup_for_test.sh
#    KINOBASE = KINOBASE + ".save"
#    REQUESTS_JSON = REQUESTS_JSON + ".save"
#    REQUESTS_DB = REQUESTS_DB + ".save"
#    logger.warning("Using temporal databases")
#else:
#    logger.warning("Using official databases")
