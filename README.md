# Python EUDR client

Powered by zeep

This is a work in progress. Contributions are welcome.

## Running integration test

The following command will trigger the test EUDR echo service, and output the response
```shell
export EUDR_AUTHENTICATION_KEY=verysecret
export EUDR_USERNAME=notsosecret
python -m py_eudr --echo
```

Expected output:
```
INFO:root:Echo response: User notsosecret, using third party system eudr-test and IP address 1.2.3.4 says: Py-EUDR
```

You can also try submitting random DDS data with `--submit-random` flag, and then retracting it with `--retract` flag.

See `python -m py_eudr --help` for more information.

