`default_nettype none

module command_fifo #(parameter DEPTH=64, parameter WIDTH=25)(
        input wire clk,
        input wire rst,
        input wire write,
        input wire [WIDTH-1:0] command_in,
        output logic full,

        output logic [WIDTH-1:0] command_out,
        input wire read,
        output logic empty
    );

    logic [$clog2(DEPTH)-1:0]   write_pointer;
    logic [$clog2(DEPTH)-1:0]   read_pointer;
    logic [WIDTH-1:0] fifo [DEPTH-1:0]; //when read asynchronously/combinationally, will result in distributed RAM usage

    always_comb begin
      empty = (read_pointer == write_pointer);
      full = (write_pointer + 1'b1 == read_pointer);

      if (!rst) begin
         command_out = fifo[read_pointer];
      end else begin
         command_out = 0;
      end
    end

    always_ff @( posedge clk ) begin
      if (rst) begin
         read_pointer <= 0;
         write_pointer <= 0;

      end else begin

         if (write && !full) begin
            fifo[write_pointer] <= command_in;
            write_pointer <= write_pointer + 1'b1;
         end

         if (read && !empty) begin
            read_pointer <= read_pointer + 1'b1;
         end

      end
    end

endmodule

`default_nettype wire