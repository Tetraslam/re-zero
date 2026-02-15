`default_nettype none

module uart_transmit #(
    parameter INPUT_CLOCK_FREQ = 240_000_000,
    parameter BAUD_RATE = 9600
) (
    input wire clk,
    input wire rst,
    input wire [7:0] din,
    input wire trigger,

    output logic busy,
    output logic dout
);
  localparam BAUD_BIT_PERIOD = INPUT_CLOCK_FREQ / BAUD_RATE;
  localparam BAUD_BIT_PERIOD_WIDTH = $rtoi($ceil($clog2(BAUD_BIT_PERIOD)));

  logic [8:0] copied_din;
  logic [BAUD_BIT_PERIOD_WIDTH-1:0] cycle_counter;
  logic [3:0] bits_transmitted;  // does not count start and end bit

  always_ff @(posedge clk) begin
    if (rst == 0) begin
      if (trigger == 1 && busy == 0) begin  // detect for start, and only allow new data to be processed when not busy
        cycle_counter <= 0;
        copied_din <= { 1'b1, din };
        bits_transmitted <= 0;

        // don't wait a cycle (send start signal)
        busy <= 1;
        dout <= 0;
      end

      if (busy == 1) begin  // main logic
        if (cycle_counter == BAUD_BIT_PERIOD - 1) begin
          cycle_counter <= 0;

          if (bits_transmitted == 9) begin  // finished transmitting bits
            busy <= 0;
            copied_din <= 0;
            bits_transmitted <= 0;
          end else begin  // still doing it, so let's continue
            dout <= copied_din[0];

            copied_din <= copied_din >> 1;
            bits_transmitted <= bits_transmitted + 1;
          end
        end else begin
          cycle_counter <= cycle_counter + 1;
        end
      end 
    end else begin  // reset
      busy <= 0;
      dout <= 1;  // data line

      cycle_counter <= 0;
      copied_din <= 0;
      bits_transmitted <= 0;
    end
  end
endmodule

`default_nettype wire