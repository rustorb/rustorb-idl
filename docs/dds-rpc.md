# DDS services (DDS-RPC)

`rustorb-idl -brust -Wbdds_only -Wbxtypes` writes the function-call style
of DDS-RPC 1.0 for the interfaces marked `@DDSService`, for rustorb-dds's
`rustorb_dds::rpc` (rustorb/rustorb-dds#72). The mapping follows the
Enhanced Service Mapping of the OMG specification (7.5.1.2).

```idl
module Calc {
    exception TooBig { long limit; };

    @DDSService
    interface Adder {
        long add(in long a, in long b) raises (TooBig);
    };

    @DDSService
    interface Calculator : Adder {
        double divide(in double a, in double b, out double remainder);
        attribute string name;
    };
};
```

## The implied IDL

The generator adds the request and reply types to the IDL it read, in the
module of each interface (`python/rustorb_idl/rpc.py`). They are written
like any struct. Every interface a service inherits from gets them too.

| Type | Members |
| --- | --- |
| `I_op_In` | the in and inout parameters, or `dds::rpc::UnusedMember dummy` |
| `I_op_Out` | the out and inout parameters, then the return value as `return_` (`return_1` if a parameter has that name), or `dummy` |
| `I_op_Result` | `@optional I_op_Out result` and `@optional E_Ex e_ex` for each exception `E` (name in lower case) |
| `I_Request` | `@optional I_op_In op` for each operation of `I` and its bases |
| `I_Reply` | `@optional I_op_Result op` for each operation, and `@optional dds::rpc::RemoteExceptionCode_t remoteEx` (`remoteEx_1` if an operation has that name) |
| `E_Ex` | the members of the exception `E` |

- An attribute `a` gives the operations `get_attribute_a` and, unless it
  is readonly, `set_attribute_a(in T a)`, which raise the exceptions of its
  `getraises` and `setraises` (7.5.1.1.3).
- The inheritance is flattened (7.5.1.2.6). The member of an inherited
  operation has the type of the interface that declares it
  (`Adder_add_In` in `Calculator_Request`).
- In and Out are `@appendable`, or `@mutable` when the operation has
  `@Mutable` (7.5.1.2.1.4). Result, Request and Reply are `@mutable` with
  every member `@optional`: the `@Choice` of 7.5.1.2.1.1, where exactly
  one member is there.
- All of them are `@autoid(HASH)` (`@Autoid`, 7.5.1.2.1.2): the member ID
  is the MD5 hash of the member name. So the members of a base's Request
  have the IDs of the same members of a derived interface's Request, and
  a client of `Adder` can call a `Calculator` service (the types are
  assignable, DDS-XTypes 7.2.4).
- IDL has no struct member of an exception type. So a Result refers to
  the struct `E_Ex`, which has the exception's members and is written next
  to the exception.
- `dds::rpc` (`UnusedMember`, `RemoteExceptionCode_t`, the headers of the
  Basic Service Mapping) is in `dds_rpc.idl` of `rustorb-idl --idl-dir`.
  The main file includes it if no file has it. The Rust code refers to the
  copy that rustorb-dds has (`rustorb_dds::rpc::idl::dds`) as an extern
  module, unless `-Wbextern=dds=...` says otherwise.

## The Rust code

For an interface `I`, in its module:

- The trait `I` has a method for each operation `I` declares. The
  traits of its bases are its supertraits. A method takes the in and inout
  parameters by value. It returns `Result<T, rustorb_dds::rpc::RpcError<X>>`:
  - `T` is the return value, or the Out struct when there are out or inout
    parameters, or `()`;
  - `X` is the enum `IOpException`, with a variant for each exception
    (`TooBig(TooBigEx)`), or `Infallible` when the operation raises
    none.
- `IClient` has a method for each operation of `I` and its bases, with
  the same signature. It sends the request and waits for the reply (10 s
  by default, `set_timeout`). A one-way operation sends and returns at
  once. Its other methods are `new`, `with_service_name`, `with_config`,
  `config`, `requester`, `wait_for_service`, `timeout` and
  `set_timeout`.
- `IServer<S: I>` takes the requests and calls `S`. `process(timeout)`
  answers the requests that come within `timeout`, and `run(&stop)`
  answers until `stop` is set. An exception of the operation is sent in
  the Result. A `RpcError::Remote(code)` is sent as `remoteEx`, and any
  other error as `REMOTE_EX_UNKNOWN_EXCEPTION`. A request with no
  operation gets `REMOTE_EX_UNKNOWN_OPERATION`, and one with more than one
  gets `REMOTE_EX_INVALID_ARGUMENT`. A one-way operation gets no reply.
- The topics are `<M>_<I>_Service_Request` and `_Reply` (7.4.1). `<M>_<I>`
  is the interface's name, with its modules joined by `_`.
  `with_service_name(p, "x")` uses `<M>_<I>_x_Request`. A server announces
  the names of its bases' topics as topic aliases (7.4.3).
- The constructors register the request and reply types, so the
  endpoints announce their TypeInformation. A service needs `-Wbxtypes`
  for this.
- The code refers to rustorb-dds by `-Wbrustorb_dds=PATH`
  (`::rustorb_dds` by default). It checks
  `rustorb_dds::rpc::GENERATED_CODE_VERSION_1`.

```rust
struct Service;

impl Adder for Service {
    fn add(&self, a: i32, b: i32) -> Result<i32, RpcError<AdderAddException>> {
        Ok(a + b)
    }
}
// impl Calculator for Service { ... }

let server = CalculatorServer::new(&participant, Service)?;
std::thread::spawn(move || server.run(&STOP));

let client = CalculatorClient::new(&participant)?;
client.wait_for_service(Duration::from_secs(5));
assert_eq!(client.add(2, 3)?, 5);
```

## A pair of types

For a service defined by a pair of types in the Basic Service Mapping
(7.3.1.4), a struct marked `@RPCRequestType` (or `@RPCReplyType`) with a
member `header` of type `dds::rpc::RequestHeader` (or `ReplyHeader`)
implements `rustorb_dds::rpc::BasicRequest` (or `BasicReply`).
rustorb-dds's `Requester::basic` and `Replier::basic` use them.

## Not done

- The Basic Service Mapping of interfaces (the `Call` and `Return` unions
  with hashed labels, 7.5.1.1). A Basic service can be written with a pair
  of types.
- The asynchronous interface (`IAsync`, 7.11.1.1.2) and the other
  languages (C++, Java, Python).
- `@DDSRequestTopic` and `@DDSReplyTopic` (7.4.2.2). The topic names can
  be given at run time with `with_config`.
- Collisions of hashed member IDs are errors, as for any `@autoid(HASH)`
  struct.
